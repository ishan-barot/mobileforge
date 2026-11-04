"""stateful orchestrator. a small explicit state machine:

  triage -> reproduce -> diagnose -> repair -> verify -> review -> finalize
                 |                      ^         |         |
                 v                      +--retry--+---------+
             needs_info                (bounded by max attempts)

agents propose, deterministic code decides. state is checkpointed after every node."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from . import agents, android
from .cases import Case
from .config import RUNS_DIR
from .context import RunContext
from .memory import FixMemory
from .state import CheckpointStore
from .tools import TOOLS
from .workspace import Runner, Workspace, create_workspace

LOAD_ERRORS = ("Failed to load", "SyntaxError", "Cannot find module", "Transform failed",
               "Failed to resolve import", "is not a function", "No test files found")


def new_run_id(case: Case, mode: str) -> str:
    return f"{case.id}-{mode}-{uuid.uuid4().hex[:6]}"


# ---------- nodes ----------

def node_triage(ctx: RunContext) -> str:
    ctx.state["spec"] = agents.triage(ctx)
    return "reproduce"


def node_reproduce(ctx: RunContext) -> str:
    ws: Workspace = ctx.ws
    if ws.case.layer == "android":
        return _reproduce_android(ctx)

    visible_ok, visible_out = ws.run_visible_suite()
    feedback = "" if visible_ok else f"note: the existing suite already fails on this code:\n{visible_out[:3000]}"
    for _ in range(2):
        try:
            out = agents.reproduce_core(ctx, ctx.state["spec"], feedback)
        except agents.AgentGaveUp:
            out = {"reproduced": False, "test_files": [], "evidence": "reproduce agent never submitted"}
        if not out.get("reproduced"):
            ctx.state.update(status="needs_info", repro={"reproduced": False, **out})
            return "finalize"
        files = [f for f in ctx.state.get("repro_tests", [])]
        if not files:
            feedback = "you said it reproduced but never wrote a repro test with write_repro_test."
            continue
        # don't trust the agent's word, run the repro tests ourselves
        ok, test_out = ws.run_tests(files)
        if ok:
            feedback = f"your test passes on the current code, so it doesn't reproduce the bug:\n{test_out[:2000]}"
            ctx.state["repro_tests"] = []
            continue
        if any(marker in test_out for marker in LOAD_ERRORS):
            feedback = f"your test crashes instead of failing an assertion. fix the test:\n{test_out[:2000]}"
            ctx.state["repro_tests"] = []
            continue
        ctx.state["repro"] = {"reproduced": True, "test_files": files, "evidence": out.get("evidence", ""),
                              "failing_output": test_out[:4000], "visible_suite_ok": visible_ok}
        return "diagnose"
    ctx.state.update(status="needs_info", repro={"reproduced": False, "evidence": feedback})
    return "finalize"


def _reproduce_android(ctx: RunContext) -> str:
    results = {}
    for flow in ctx.ws.case.repro_flows:
        try:
            results[flow] = TOOLS["run_maestro"].fn(ctx, {"flow_id": flow})
        except Exception as e:
            results[flow] = f"FAILED\n{e}"
    ctx.log("tool", "reproduce", tool="run_maestro", input=list(results), output=json.dumps(results)[:3000])
    failing = {k: v for k, v in results.items() if v.startswith("FAILED")}
    if not failing:
        ctx.state.update(status="needs_info", repro={"reproduced": False,
                                                      "evidence": "every approved flow passed. need steps that show the bug."})
        return "finalize"
    ctx.state["repro"] = {"reproduced": True, "flows": list(failing), "failing_output": json.dumps(failing)[:5000],
                          "screenshots": ctx.state.get("screenshots", [])[-6:]}
    return "diagnose"


def node_diagnose(ctx: RunContext) -> str:
    hits = ""
    if ctx.memory is not None:
        spec = ctx.state["spec"]
        query = f"{ctx.ws.case.bug_report} {spec.get('component', '')} {spec.get('observed', '')}"
        found = ctx.memory.search(query, category=ctx.ws.case.category, exclude_case=ctx.case_id_for_memory)
        ctx.state["memory_hits"] = [h["id"] for h in found]
        hits = "\n\n".join(f"- bug: {h['bug_report'][:200]}\n  root cause: {h['root_cause']}\n"
                           f"  patch:\n{h['diff'][:1200]}" for h in found)
    ctx.state["diagnosis"] = agents.diagnose(ctx, ctx.state["spec"], ctx.state["repro"].get("failing_output", ""), hits)
    ctx.state["root_cause"] = ctx.state["diagnosis"].get("root_cause")
    ctx.state["relevant_files"] = ctx.state["diagnosis"].get("files", [])
    return "repair"


def node_repair(ctx: RunContext) -> str:
    ctx.state["attempt_count"] = ctx.state.get("attempt_count", 0) + 1
    try:
        ctx.state["repair"] = agents.repair(ctx, ctx.state["spec"], ctx.state["diagnosis"], ctx.state.get("feedback", ""))
    except agents.AgentGaveUp:
        ctx.state["repair"] = {"summary": "repair agent never submitted"}
    return "verify"


def run_checks(ctx: RunContext) -> dict:
    """the deterministic gate. a patch only passes if the original failure is gone and nothing else broke."""
    ws: Workspace = ctx.ws
    checks: dict = {"source_changed": bool(ws.source_changes())}
    if not checks["source_changed"]:
        checks["passed"] = False
        return checks
    if ws.case.layer == "core":
        repro = ctx.state.get("repro_tests", [])
        if repro:
            ok, out = ws.run_tests(repro)
            checks["repro_fixed"] = {"ok": ok, "output": out[-2500:]}
        ok, out = ws.run_visible_suite()
        checks["regression_suite"] = {"ok": ok, "output": out[-2500:]}
        ok, out = ws.run_typecheck()
        checks["typecheck"] = {"ok": ok, "output": out[-1500:]}
    else:
        ctx.state["app_built_from_current_code"] = False
        for flow in ws.case.repro_flows:
            try:
                out = TOOLS["run_maestro"].fn(ctx, {"flow_id": flow})
            except Exception as e:
                out = f"FAILED\n{e}"
            checks[f"flow:{flow}"] = {"ok": out.startswith("PASSED"), "output": out[-2500:]}
    checks["passed"] = all(v["ok"] for k, v in checks.items() if isinstance(v, dict))
    return checks


def node_verify(ctx: RunContext) -> str:
    checks = run_checks(ctx)
    ctx.state["test_results"] = checks
    ctx.log("verify", "orchestrator", checks={k: (v["ok"] if isinstance(v, dict) else v) for k, v in checks.items()})
    if checks["passed"]:
        return "review"
    if not checks["source_changed"]:
        ctx.state["feedback"] = "you didn't change any source file."
    else:
        ctx.state["feedback"] = "\n\n".join(f"{k}: FAILED\n{v['output']}" for k, v in checks.items()
                                            if isinstance(v, dict) and not v["ok"])
    if ctx.state["attempt_count"] < ctx.state["max_attempts"]:
        return "repair"
    ctx.state["status"] = "failed"
    return "finalize"


def node_review(ctx: RunContext) -> str:
    diff = ctx.ws.diff(include_repro=True)  # the fix plus its regression test
    try:
        verdict = agents.review(ctx, ctx.state["spec"], diff,
                                {k: v["ok"] for k, v in ctx.state["test_results"].items() if isinstance(v, dict)})
    except agents.AgentGaveUp:
        verdict = {"blocking_issues": [{"file": "-", "problem": "reviewer never submitted", "why_it_breaks": "-"}],
                   "notes": []}
    # code decides, not the reviewer's mood: approved if and only if no concrete blocking issue was listed
    blocking = [b for b in verdict.get("blocking_issues", []) if isinstance(b, dict) and b.get("problem")]
    verdict["approve"] = not blocking
    ctx.state["review"] = verdict
    ctx.state["review_rounds"] = ctx.state.get("review_rounds", 0) + 1
    if verdict["approve"]:
        ctx.state["status"] = "awaiting_approval"
        return "finalize"
    ctx.state["feedback"] = "code review found blocking issues. fix only these:\n" + json.dumps(blocking, indent=2)
    if ctx.state["attempt_count"] < ctx.state["max_attempts"]:
        return "repair"
    ctx.state["status"] = "rejected_by_review"
    return "finalize"


def node_single(ctx: RunContext) -> str:
    try:
        ctx.state["single"] = agents.single_agent(ctx)
        ctx.state["root_cause"] = ctx.state["single"].get("root_cause")
    except agents.AgentGaveUp:
        ctx.state["single"] = {"summary": "agent ran out of turns"}
    ctx.state["attempt_count"] = 1
    checks = run_checks(ctx)
    ctx.state["test_results"] = checks
    ctx.state["status"] = "awaiting_approval" if checks["passed"] else "failed"
    return "finalize"


def node_finalize(ctx: RunContext) -> str:
    ws: Workspace = ctx.ws
    ctx.state.setdefault("status", "failed")
    # the delivered patch ships the repro test as its regression test, like a human pr would
    diff = ws.diff(include_repro=True) if ws.source_changes() else ""
    (ctx.run_dir / "fix.patch").write_text(diff, encoding="utf-8")
    ctx.state["patch_path"] = str(ctx.run_dir / "fix.patch")
    ctx.state["lines_changed"] = sum(1 for l in diff.splitlines()
                                     if l[:1] in "+-" and not l.startswith(("+++", "---")))
    ctx.state["files_changed"] = ws.source_changes()

    # regression: did the final code break the visible suite?
    if ws.case.layer == "core" and ctx.state["files_changed"]:
        ok, _ = ws.run_visible_suite()
        ctx.state["regression"] = not ok

    # hidden acceptance tests, benchmark only, never shown to any agent
    if ws.case.is_benchmark:
        hidden = None
        if ws.case.layer == "core":
            hidden = ws.run_hidden()
        elif ws.case.hidden_flow and ctx.state["files_changed"]:
            if not ctx.state.get("app_built_from_current_code"):
                android.build_and_install(ws.repo, ctx.settings.mobile_build_timeout)
            hidden = android.run_flow(ws.case.dir / ws.case.hidden_flow, ctx.run_dir / "maestro" / "hidden")
        elif ws.case.hidden_flow:
            hidden = (False, "no source changes")
        if hidden is not None:
            ctx.state["hidden_pass"], hidden_out = hidden
            (ctx.run_dir / "hidden-tests.txt").write_text(hidden_out, encoding="utf-8")
        ctx.state["verified"] = bool(ctx.state.get("hidden_pass")) and ctx.state["status"] == "awaiting_approval"

        if ctx.state["verified"] and ctx.memory is not None:
            ctx.memory.add(case_id=ws.case.id, category=ws.case.category,
                           component=ctx.state.get("spec", {}).get("component", ws.case.layer),
                           bug_report=ws.case.bug_report, root_cause=ctx.state.get("root_cause") or "",
                           diff=diff, files=ctx.state["files_changed"],
                           validation={"hidden": True, "checks": True}, source="benchmark-verified")

    ctx.state["finished"] = time.time()
    ctx.state["duration_s"] = round(ctx.state["finished"] - ctx.state["started"], 1)
    from .report import write_run_report
    write_run_report(ctx.run_dir, ctx.state)
    return "done"


NODES = {"triage": node_triage, "reproduce": node_reproduce, "diagnose": node_diagnose,
         "repair": node_repair, "verify": node_verify, "review": node_review,
         "single": node_single, "finalize": node_finalize}


# ---------- driver ----------

def execute(ctx: RunContext, store: CheckpointStore, log=print) -> dict:
    from .report import write_run_report
    while ctx.state["next"] != "done":
        node = ctx.state["next"]
        log(f"  -> {node}")
        ctx.log("node", "orchestrator", node=node)
        try:
            ctx.state["next"] = NODES[node](ctx)
        except Exception as e:
            ctx.state.update(status="error", error=f"{type(e).__name__}: {e}")
            ctx.log("error", "orchestrator", node=node, error=str(e))
            store.save(ctx.run_id, node, ctx.state)
            write_run_report(ctx.run_dir, ctx.state)
            raise
        ctx.sync_usage()
        store.save(ctx.run_id, node, ctx.state)
        write_run_report(ctx.run_dir, ctx.state)
    return ctx.state


def start_run(case: Case, mode: str, llm, settings, runner: Runner | None = None, memory: FixMemory | None = None,
              store: CheckpointStore | None = None, ws: Workspace | None = None, run_id: str | None = None,
              log=print) -> dict:
    assert mode in ("single", "multi", "full")
    store = store or CheckpointStore()
    runner = runner or Runner(settings.command_timeout, settings.mobile_build_timeout)
    run_id = run_id or new_run_id(case, mode)
    run_dir = RUNS_DIR / run_id
    log(f"run {run_id}")
    ws = ws or create_workspace(case, run_id, runner, log)
    state = {"run_id": run_id, "case": case.to_dict(), "mode": mode, "model": llm.model,
             "issue_id": case.id, "bug_report": case.bug_report, "status": "running",
             "next": "single" if mode == "single" else "triage", "attempt_count": 0,
             "max_attempts": settings.max_repair_attempts, "started": time.time(),
             "repo_path": str(ws.repo), "run_dir": str(run_dir), "approval_status": "pending",
             "visible_tests": ws.visible_tests}
    ctx = RunContext(run_id, run_dir, ws, llm, settings, state, memory=memory if mode == "full" else None)
    store.save(run_id, "start", state)
    return execute(ctx, store, log)


def resume_run(run_id: str, llm, settings, runner: Runner | None = None, memory: FixMemory | None = None,
               store: CheckpointStore | None = None, log=print) -> dict:
    store = store or CheckpointStore()
    state = store.latest(run_id)
    if state is None:
        raise RuntimeError(f"no checkpoints for {run_id}")
    if state["next"] == "done":
        log("that run already finished")
        return state
    if state.get("status") == "error":
        state["status"] = "running"
        node = [n for _, n in store.history(run_id)][-1]
        # the crashed node never advanced `next`, so it re-runs from the top of that node
        log(f"resuming after a crash in {node}")
    case = Case.from_dict(state["case"])
    runner = runner or Runner(settings.command_timeout, settings.mobile_build_timeout)
    ws = Workspace(Path(state["repo_path"]), case, runner)
    ws.visible_tests = state.get("visible_tests", ws.visible_tests)
    ctx = RunContext(run_id, Path(state["run_dir"]), ws, llm, settings, state,
                     memory=memory if state["mode"] == "full" else None)
    return execute(ctx, store, log)
