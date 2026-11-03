"""end-to-end tests of the orchestrator with a scripted model and a fake test runner.
no api key, no node, no emulator needed. run with: python -m unittest discover tests"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from mobileforge import bench, orchestrator
from mobileforge.cases import Case
from mobileforge.config import Settings
from mobileforge.llm import ScriptedProvider, tool_call
from mobileforge.memory import FixMemory
from mobileforge.state import CheckpointStore
from mobileforge.tools import TOOLS, ToolError
from mobileforge.workspace import Workspace

BROKEN = "export const add = (a: number, b: number) => a - b;\n"
FIXED_LINE = "a + b"


class FakeRunner:
    """pretends to be vitest: everything passes once calc.ts is fixed."""

    def __init__(self):
        self.calls = []

    def install(self, repo, layer):
        return 0, "ok"

    def vitest(self, package_dir, files):
        self.calls.append(files)
        src = (Path(package_dir) / "src" / "calc.ts").read_text()
        if FIXED_LINE in src:
            return 0, f"PASS {files}"
        return 1, "FAIL  AssertionError: expected -1 to be 5"

    def typecheck(self, package_dir):
        return 0, "ok"


def make_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    (repo / "packages/core/src").mkdir(parents=True)
    (repo / "packages/core/test").mkdir(parents=True)
    (repo / "packages/core/src/calc.ts").write_text(BROKEN)
    (repo / "packages/core/test/calc.test.ts").write_text("// visible test\n")
    (repo / "node_modules").mkdir()
    (repo / "node_modules/secret.ts").write_text("nope")
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    return repo


def make_case(tmp: Path, cid="core-99") -> Case:
    d = tmp / "case"
    d.mkdir()
    (d / "hidden.test.ts").write_text("// hidden test\n")
    return Case(id=cid, title="add subtracts", layer="core", category="logic",
                bug_report="add(2, 3) returns -1 instead of 5", dir=d, hidden_test="hidden.test.ts")


def by_agent(book: dict):
    """route scripted responses by which agent is asking."""
    names = {"triage": "triage", "reproduce": "reproduce", "root cause": "diagnose", "write the fix": "repair",
             "code review": "review", "whole job alone": "single"}

    def respond(system, messages, tools):
        agent = next(v for k, v in names.items() if k in system)
        queue = book[agent]
        if not queue:
            raise AssertionError(f"{agent} asked for more responses than scripted")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    return respond


SPEC = {"expected": "5", "observed": "-1", "component": "calc", "reproduction_steps": "call add(2,3)",
        "acceptance_criteria": ["add(2,3) === 5"], "search_terms": ["add"]}
DIAG = {"root_cause": "uses minus", "evidence": "calc.ts line 1", "confidence": "high",
        "files": ["packages/core/src/calc.ts"], "suggested_fix": "use plus"}
FIX = tool_call("replace_in_file", {"path": "packages/core/src/calc.ts", "old": "a - b", "new": "a + b"})
WRONG_FIX = tool_call("replace_in_file", {"path": "packages/core/src/calc.ts", "old": "a - b", "new": "b - a"})
UNDO_WRONG = tool_call("replace_in_file", {"path": "packages/core/src/calc.ts", "old": "b - a", "new": "a + b"})


def happy_book():
    return {
        "triage": [tool_call("submit", SPEC)],
        "reproduce": [tool_call("write_repro_test", {"name": "add", "content": "test"}),
                      tool_call("submit", {"reproduced": True, "test_files": ["test/mobileforge/add.test.ts"],
                                           "evidence": "fails"})],
        "diagnose": [tool_call("submit", DIAG)],
        "repair": [FIX, tool_call("submit", {"summary": "plus", "rationale": "math"})],
        "review": [tool_call("submit", {"approve": True, "risks": [], "unnecessary_changes": [], "notes": "ok"})],
    }


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.tmp)
        self.case = make_case(self.tmp)
        self.runner = FakeRunner()
        self.ws = Workspace(self.repo, self.case, self.runner)
        self.store = CheckpointStore(self.tmp / "state.db")
        self.settings = Settings(model="scripted", api_key=None, max_repair_attempts=3,
                                 command_timeout=60, mobile_build_timeout=60)
        orchestrator.RUNS_DIR = self.tmp / "runs"

    def start(self, book, mode="multi", memory=None, run_id="r1"):
        return orchestrator.start_run(self.case, mode, ScriptedProvider(by_agent(book)), self.settings,
                                      runner=self.runner, memory=memory, store=self.store, ws=self.ws,
                                      run_id=run_id, log=lambda *_: None)

    def test_happy_path_multi_agent(self):
        s = self.start(happy_book())
        self.assertEqual(s["status"], "awaiting_approval")
        self.assertTrue(s["hidden_pass"])
        self.assertTrue(s["verified"])
        self.assertFalse(s["regression"])
        self.assertEqual(s["attempt_count"], 1)
        self.assertIn("+export const add = (a: number, b: number) => a + b;", Path(s["patch_path"]).read_text())
        self.assertNotIn("mobileforge/add.test.ts", Path(s["patch_path"]).read_text())  # repro tests stay out of the patch
        self.assertTrue((self.tmp / "runs/r1/report.html").exists())
        nodes = [n for _, n in self.store.history("r1")]
        self.assertEqual(nodes, ["start", "triage", "reproduce", "diagnose", "repair", "verify", "review", "finalize"])
        self.assertFalse((self.repo / "packages/core/test/__mf_hidden__.test.ts").exists())

    def test_failed_verification_retries_with_evidence(self):
        book = happy_book()
        book["repair"] = [WRONG_FIX, tool_call("submit", {"summary": "x", "rationale": "x"}),
                          UNDO_WRONG, tool_call("submit", {"summary": "plus", "rationale": "math"})]
        provider = ScriptedProvider(by_agent(book))
        s = orchestrator.start_run(self.case, "multi", provider, self.settings, runner=self.runner,
                                   store=self.store, ws=self.ws, run_id="r2", log=lambda *_: None)
        self.assertEqual(s["status"], "awaiting_approval")
        self.assertEqual(s["attempt_count"], 2)
        second_repair_prompt = [c for c in provider.seen if "write the fix" in c["system"]][2]["messages"][0]["content"]
        self.assertIn("failed verification", second_repair_prompt)

    def test_attempts_are_bounded(self):
        book = happy_book()
        book["repair"] = [WRONG_FIX, tool_call("submit", {"summary": "x", "rationale": "x"})] + \
                         [tool_call("submit", {"summary": "x", "rationale": "x"})] * 2
        s = self.start(book, run_id="r3")
        self.assertEqual(s["status"], "failed")
        self.assertEqual(s["attempt_count"], 3)
        self.assertFalse(s["verified"])

    def test_review_rejection_counts_as_safe_failure(self):
        book = happy_book()
        reject = tool_call("submit", {"approve": False, "risks": ["games the test"], "unnecessary_changes": [], "notes": "no"})
        book["review"] = [reject] * 3
        book["repair"] = [FIX, tool_call("submit", {"summary": "p", "rationale": "m"})] + \
                         [tool_call("submit", {"summary": "p", "rationale": "m"})] * 2
        s = self.start(book, run_id="r4")
        self.assertEqual(s["status"], "rejected_by_review")
        self.assertTrue(s["hidden_pass"])
        self.assertFalse(s["verified"])  # a rejected patch is never counted as a delivered fix

    def test_cannot_reproduce_asks_for_info(self):
        book = happy_book()
        book["reproduce"] = [tool_call("submit", {"reproduced": False, "test_files": [], "evidence": "",
                                                  "missing_info": "which inputs?"})]
        s = self.start(book, run_id="r5")
        self.assertEqual(s["status"], "needs_info")
        self.assertEqual(s["files_changed"], [])

    def test_repro_that_passes_is_rejected(self):
        # a "repro" test that passes on buggy code isn't a reproduction
        self.runner.vitest = lambda pkg, files: (0, "PASS")
        book = happy_book()
        book["reproduce"] = [tool_call("write_repro_test", {"name": "a", "content": "t"}),
                             tool_call("submit", {"reproduced": True, "test_files": [], "evidence": "x"})] * 2
        s = self.start(book, run_id="r6")
        self.assertEqual(s["status"], "needs_info")

    def test_resume_after_crash(self):
        book = happy_book()
        book["diagnose"] = [RuntimeError("power cut")]
        with self.assertRaises(RuntimeError):
            self.start(book, run_id="r7")
        self.assertEqual(self.store.latest("r7")["status"], "error")
        fresh = happy_book()
        s = orchestrator.resume_run("r7", ScriptedProvider(by_agent({"diagnose": fresh["diagnose"],
                                    "repair": fresh["repair"], "review": fresh["review"]})),
                                    self.settings, runner=self.runner, store=self.store, log=lambda *_: None)
        self.assertEqual(s["status"], "awaiting_approval")
        self.assertTrue(s["verified"])

    def test_full_mode_saves_verified_fix_to_memory(self):
        mem = FixMemory(self.tmp / "mem.db")
        s = self.start(happy_book(), mode="full", memory=mem, run_id="r8")
        self.assertTrue(s["verified"])
        rows = mem.all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(mem.search("add returns wrong number", exclude_case="core-99"), [])
        self.assertEqual(len(mem.search("add returns wrong number subtract")), 1)

    def test_single_agent_baseline(self):
        book = {"single": [tool_call("read_source", {"path": "packages/core/src/calc.ts"}), FIX,
                           tool_call("run_tests", {}), tool_call("submit", {"summary": "s", "root_cause": "minus"})]}
        s = self.start(book, mode="single", run_id="r9")
        self.assertEqual(s["status"], "awaiting_approval")
        self.assertTrue(s["verified"])


class SafetyTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        case = make_case(tmp)
        self.ws = Workspace(make_repo(tmp), case, FakeRunner())

        class Ctx:
            pass
        self.ctx = Ctx()
        self.ctx.ws, self.ctx.state, self.ctx.edit_budget = self.ws, {}, None

    def call(self, tool, args):
        return TOOLS[tool].fn(self.ctx, args)

    def test_cannot_edit_outside_editable_paths(self):
        with self.assertRaises(ToolError):
            self.call("replace_in_file", {"path": "packages/core/test/calc.test.ts", "old": "visible", "new": "x"})

    def test_cannot_escape_repo_or_read_blocked_folders(self):
        for path in ["../../etc/passwd", "node_modules/secret.ts", ".git/config"]:
            with self.assertRaises(ToolError):
                self.call("read_source", {"path": path})

    def test_test_paths_are_allowlisted(self):
        for bad in ["../evil.test.ts", "test/../../x.test.ts", "src/calc.ts"]:
            with self.assertRaises(ToolError):
                self.call("run_tests", {"files": [bad]})

    def test_hidden_test_file_is_invisible(self):
        with self.assertRaises(ToolError):
            self.call("read_source", {"path": "packages/core/test/__mf_hidden__.test.ts"})

    def test_edit_budget(self):
        self.ctx.edit_budget = 1
        self.call("replace_in_file", {"path": "packages/core/src/calc.ts", "old": "a - b", "new": "b - a"})
        with self.assertRaises(ToolError):
            self.call("replace_in_file", {"path": "packages/core/src/calc.ts", "old": "b - a", "new": "a + b"})

    def test_ambiguous_edit_rejected(self):
        with self.assertRaises(ToolError):
            self.call("replace_in_file", {"path": "packages/core/src/calc.ts", "old": "number", "new": "int"})

    def test_maestro_flows_are_allowlisted(self):
        with self.assertRaises(ToolError):
            self.call("run_maestro", {"flow_id": "anything"})


class BenchTest(unittest.TestCase):
    def test_summary_math(self):
        tmp = Path(tempfile.mkdtemp())
        bench.RESULTS_DIR = tmp
        outcomes = {"single": [True, False], "multi": [True, True], "full": [True, True]}

        def fake_start(case, mode, llm, settings, runner=None, memory=None, log=None):
            ok = outcomes[mode].pop(0)
            return {"run_id": f"{case.id}-{mode}", "status": "awaiting_approval" if ok else "failed",
                    "verified": ok, "hidden_pass": ok, "lines_changed": 1, "duration_s": 10, "cost_usd": 0.01,
                    "repro": {"reproduced": True}, "attempt_count": 1, "tool_calls": 5}
        cases = [Case("c1", "t", "core", "logic", "b"), Case("c2", "t", "core", "logic", "b")]
        bench.run_benchmark(cases, ["single", "multi", "full"], 1, None, None, log=lambda *_: None,
                            start_fn=fake_start, cleanup_fn=lambda _: None)
        c = json.loads((tmp / "comparison.json").read_text())
        self.assertEqual(c["modes"]["single"]["verified_repair_rate"], 0.5)
        self.assertEqual(c["modes"]["multi"]["verified_repair_rate"], 1.0)
        self.assertEqual(c["multi_vs_single_pp"], 50.0)
        self.assertEqual(c["memory_benefit_pp"], 0.0)
        self.assertTrue((tmp / "summary.md").exists())


if __name__ == "__main__":
    unittest.main()


class AgentLoopTest(unittest.TestCase):
    def test_never_forces_tool_choice_and_grace_turns_only_offer_submit(self):
        from mobileforge import agents
        from mobileforge.context import RunContext
        seen = []

        class P(ScriptedProvider):
            def chat(self, system, messages, tools, tool_choice=None, max_tokens=4096):
                seen.append((tool_choice, [t["name"] for t in tools]))
                if len(seen) < 3:
                    return tool_call("list_files", {})
                return tool_call("submit", {"x": 1})
        tmp = Path(tempfile.mkdtemp())
        ws = Workspace(make_repo(tmp), make_case(tmp), FakeRunner())
        ctx = RunContext("a", tmp / "run", ws, P([]), None, {})
        out = agents.run_agent(ctx, "t", "sys", "go", [TOOLS["list_files"]], {"type": "object"}, max_turns=3)
        self.assertEqual(out, {"x": 1})
        self.assertTrue(all(c is None for c, _ in seen))
        self.assertEqual(seen[2][1], ["submit"])
