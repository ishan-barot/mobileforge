"""command line entry point: `mobileforge <command>`"""

from __future__ import annotations

import argparse
import shutil
import sys

from . import proc
from .config import BASE_REPO, RUNS_DIR, Settings


def cmd_doctor(args) -> int:
    s = Settings.load()
    checks = [
        ("python 3.12+", sys.version_info >= (3, 12), "install python 3.13 from python.org"),
        ("git", bool(proc.which("git")), "install git from git-scm.com"),
        ("node", bool(proc.which("node")), "install node 22 LTS from nodejs.org"),
        ("pnpm", bool(proc.which("pnpm")), "run: npm install -g pnpm"),
        ("ANTHROPIC_API_KEY in .env", bool(s.api_key), "create .env with ANTHROPIC_API_KEY=sk-ant-..."),
        ("fineprint clone", (BASE_REPO / ".git").exists(), "run: mobileforge setup"),
        ("adb (android only)", bool(proc.which("adb")), "add %LOCALAPPDATA%\\Android\\Sdk\\platform-tools to PATH"),
        ("java (android only)", bool(proc.which("java")), "set JAVA_HOME to android studio's jbr folder"),
        ("maestro (android only)", bool(proc.which("maestro")), "unzip maestro and add its bin folder to PATH"),
    ]
    for name, ok, fix in checks:
        print(f"  [{'ok' if ok else '--'}] {name}" + ("" if ok else f"   -> {fix}"))
    if proc.which("adb"):
        from .android import device_ready
        ok, _ = device_ready()
        print(f"  [{'ok' if ok else '--'}] emulator running (android only)" + ("" if ok else "   -> start it in android studio device manager"))
    print(f"\n  model: {s.model}")
    core_ok = all(ok for (name, ok, _) in checks[:6])
    print("\n  core cases ready to run" if core_ok else "\n  fix the core items above first")
    return 0 if core_ok else 1


def cmd_setup(args) -> int:
    from .workspace import setup_base
    repo = setup_base()
    print("installing fineprint dependencies once so every run after this is fast ...")
    code, out = proc.run(["pnpm", "install", "--frozen-lockfile"], repo, timeout=1800)
    print(proc.clip(out, 3000))
    if code != 0:
        print("pnpm install failed, see above")
        return 1
    print(f"\nready. fineprint is at {repo}")
    return 0


def cmd_cases(args) -> int:
    from .cases import all_cases
    for c in all_cases(args.layer):
        print(f"  {c.id:<12} {c.layer:<8} {c.category:<10} {c.title}")
    return 0


def _llm(settings):
    from .llm import make_provider
    return make_provider(settings)


def cmd_run(args) -> int:
    from .cases import adhoc_case, load_case
    from .memory import FixMemory
    from .orchestrator import start_run
    from .workspace import remove_workspace
    s = Settings.load()
    case = load_case(args.case) if args.case else adhoc_case(args.issue, args.layer)
    state = start_run(case, args.mode, _llm(s), s, memory=FixMemory() if args.mode == "full" else None)
    _print_result(state)
    if not args.keep and state.get("next") == "done" and case.is_benchmark:
        remove_workspace(state["run_id"])
    return 0


def _print_result(state: dict) -> None:
    print(f"\nstatus: {state.get('status')}")
    if "hidden_pass" in state:
        print(f"hidden acceptance tests: {'PASS' if state['hidden_pass'] else 'FAIL'}")
    print(f"attempts: {state.get('attempt_count')}  tool calls: {state.get('tool_calls', 0)}  "
          f"cost: ${state.get('cost_usd', 0):.3f}  time: {state.get('duration_s')}s")
    print(f"report: {RUNS_DIR / state['run_id'] / 'report.html'}")
    if state.get("status") == "awaiting_approval" and not state["case"].get("dir"):
        print(f"\nlooks good? run: mobileforge approve {state['run_id']}")


def cmd_resume(args) -> int:
    from .memory import FixMemory
    from .orchestrator import resume_run
    s = Settings.load()
    _print_result(resume_run(args.run_id, _llm(s), s, memory=FixMemory()))
    return 0


def cmd_approve(args) -> int:
    """human approval: save the fix into memory and say how to apply it to fineprint."""
    from .memory import FixMemory
    from .state import CheckpointStore
    store = CheckpointStore()
    state = store.latest(args.run_id)
    if not state or state.get("status") != "awaiting_approval":
        print("only runs with status awaiting_approval can be approved")
        return 1
    diff = open(state["patch_path"], encoding="utf-8").read()
    FixMemory().add(case_id=state["case"]["id"], category=state["case"]["category"],
                    component=state.get("spec", {}).get("component", state["case"]["layer"]),
                    bug_report=state["bug_report"], root_cause=state.get("root_cause") or "", diff=diff,
                    files=state.get("files_changed", []), validation={"human_approved": True}, source="human")
    state["approval_status"] = "approved"
    state["status"] = "approved"
    store.save(args.run_id, "approve", state)
    print("approved and saved to fix memory.")
    print(f"to apply it to your fineprint repo:\n  cd <your fineprint folder>\n  git apply \"{state['patch_path']}\"")
    return 0


def cmd_bench(args) -> int:
    from .bench import run_benchmark
    from .cases import all_cases, load_case
    s = Settings.load()
    cases = [load_case(c) for c in args.cases.split(",")] if args.cases else all_cases(args.layer)
    modes = args.modes.split(",")
    est = len(cases) * len(modes) * args.trials
    print(f"{len(cases)} cases x {len(modes)} modes x {args.trials} trials = {est} runs on {s.model}")
    out = run_benchmark(cases, modes, args.trials, _llm(s), s, keep=args.keep)
    print(f"\nraw rows: {out}\nsummary: {out.parent / 'summary.md'}")
    print((out.parent / "summary.md").read_text(encoding="utf-8"))
    return 0


def cmd_report(args) -> int:
    from .bench import summarize
    from .config import RESULTS_DIR
    summarize()
    print((RESULTS_DIR / "summary.md").read_text(encoding="utf-8"))
    return 0


def cmd_serve(args) -> int:
    from .server import serve
    serve(args.port)
    return 0


def cmd_clean(args) -> int:
    from .workspace import remove_workspace
    if RUNS_DIR.exists():
        for d in RUNS_DIR.iterdir():
            if (d / "repo").exists():
                remove_workspace(d.name)
                print(f"removed worktree {d.name}")
    if args.all and RUNS_DIR.exists():
        shutil.rmtree(RUNS_DIR, ignore_errors=True)
        print("deleted all run folders")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mobileforge", description="autonomous multi-agent bug repair for Fineprint")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check that everything is installed").set_defaults(fn=cmd_doctor)
    sub.add_parser("setup", help="clone fineprint and install its dependencies").set_defaults(fn=cmd_setup)
    c = sub.add_parser("cases", help="list benchmark cases")
    c.add_argument("--layer", default="all", choices=["all", "core", "android"])
    c.set_defaults(fn=cmd_cases)

    r = sub.add_parser("run", help="fix one bug")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--case", help="benchmark case id, e.g. core-01")
    g.add_argument("--issue", help="a real bug report in plain english, runs on fineprint main")
    r.add_argument("--layer", default="core", choices=["core", "android"])
    r.add_argument("--mode", default="multi", choices=["single", "multi", "full"])
    r.add_argument("--keep", action="store_true", help="keep the worktree after the run")
    r.set_defaults(fn=cmd_run)

    rs = sub.add_parser("resume", help="resume a crashed or interrupted run")
    rs.add_argument("run_id")
    rs.set_defaults(fn=cmd_resume)
    a = sub.add_parser("approve", help="approve a fix and save it to memory")
    a.add_argument("run_id")
    a.set_defaults(fn=cmd_approve)

    b = sub.add_parser("bench", help="run the benchmark")
    b.add_argument("--modes", default="single,multi,full")
    b.add_argument("--trials", type=int, default=1)
    b.add_argument("--layer", default="core", choices=["all", "core", "android"])
    b.add_argument("--cases", help="comma separated case ids")
    b.add_argument("--keep", action="store_true")
    b.set_defaults(fn=cmd_bench)

    sub.add_parser("report", help="rebuild results/summary.md from results/runs.csv").set_defaults(fn=cmd_report)
    sv = sub.add_parser("serve", help="open the local dashboard")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(fn=cmd_serve)
    cl = sub.add_parser("clean", help="remove leftover worktrees")
    cl.add_argument("--all", action="store_true", help="also delete run reports")
    cl.set_defaults(fn=cmd_clean)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except proc.CommandMissing as e:
        print(f"missing tool: {e}. run `mobileforge doctor`.")
        return 1
    except KeyboardInterrupt:
        print("\nstopped. resume later with `mobileforge resume <run-id>`")
        return 130
    except Exception as e:  # show a readable message instead of a traceback
        from .llm import LLMError
        if isinstance(e, (LLMError, RuntimeError, FileNotFoundError)):
            print(f"error: {e}")
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
