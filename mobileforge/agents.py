"""the five specialist agents plus the shared tool-calling loop.

each agent has a narrow job, a narrow tool set, and must finish by calling `submit` with
structured output. anything that decides pass/fail lives in orchestrator.py, not here."""

from __future__ import annotations

import json

from .context import RunContext
from .tools import TOOLS, ToolError, pick

SUBMIT = "submit"


class AgentGaveUp(RuntimeError):
    pass


def run_agent(ctx: RunContext, name: str, system: str, prompt: str, tools, submit_schema: dict,
              max_turns: int = 12, max_tokens: int = 4096) -> dict:
    tool_map = {t.name: t for t in tools}
    specs = [t.spec for t in tools] + [{
        "name": SUBMIT, "description": "finish your job and hand back your result. call this exactly once.",
        "input_schema": submit_schema,
    }]
    messages: list = [{"role": "user", "content": prompt}]
    ctx.log("agent_start", name, prompt=prompt[:2000])

    # some models reject forced tool_choice, so we never force it. the tool list also never changes
    # mid-conversation (that breaks thinking signatures). when turns run out we just tell it to submit
    for turn in range(max_turns + 2):
        if turn >= max_turns - 1:
            _nudge(messages, "You're out of turns. Call submit now with your best result.")
        res = ctx.llm.chat(system, messages, specs, max_tokens=max_tokens)
        u = res.get("usage", {})
        ctx.usage.add(name, u.get("input_tokens", 0), u.get("output_tokens", 0))
        ctx.sync_usage()
        content = res.get("content", [])
        messages.append({"role": "assistant", "content": content})
        for block in content:
            if block.get("type") == "text" and block["text"].strip():
                ctx.log("thought", name, text=block["text"][:2000])

        calls = [b for b in content if b.get("type") == "tool_use"]
        if not calls:
            messages.append({"role": "user", "content": "Use a tool, or call submit when you're done."})
            continue

        results = []
        for call in calls:
            if call["name"] == SUBMIT:
                ctx.log("submit", name, output=call["input"])
                return call["input"]
            tool = tool_map.get(call["name"])
            try:
                if tool is None:
                    raise ToolError(f"unknown tool {call['name']}")
                out, err = tool.fn(ctx, call["input"] or {}), False
            except ToolError as e:
                out, err = f"error: {e}", True
            except Exception as e:  # a tool crashing shouldn't kill the run, the agent can adapt
                out, err = f"error: {type(e).__name__}: {e}", True
            out = str(out)
            ctx.log("tool", name, tool=call["name"], input=call["input"], output=out[:3000], error=err)
            results.append({"type": "tool_result", "tool_use_id": call["id"], "content": out[:12000],
                            "is_error": err})
        messages.append({"role": "user", "content": results})

    raise AgentGaveUp(f"{name} never submitted")


def _nudge(messages: list, text: str) -> None:
    # tack the reminder onto the last user turn so user/assistant turns keep alternating
    last = messages[-1]
    if last["role"] != "user":
        messages.append({"role": "user", "content": text})
    elif isinstance(last["content"], str):
        if text not in last["content"]:
            last["content"] += "\n\n" + text
    elif not any(b.get("type") == "text" and b.get("text") == text for b in last["content"]):
        last["content"].append({"type": "text", "text": text})


def _j(x) -> str:
    return json.dumps(x, indent=2, default=str)


ARR = {"type": "array", "items": {"type": "string"}}
STR = {"type": "string"}

BASE = ("You are part of MobileForge, an automated bug-fixing pipeline for Fineprint, a TypeScript "
        "monorepo (packages/core = shared bill logic, apps/mobile = Expo React Native app, apps/web = Next.js). "
        "Be precise and evidence-driven. Never guess file contents, read them.")


# ---------- 1. triage ----------

def triage(ctx: RunContext) -> dict:
    case = ctx.ws.case
    schema = {"type": "object", "required": ["expected", "observed", "component", "acceptance_criteria",
                                             "search_terms", "reproduction_steps"],
              "properties": {"expected": STR, "observed": STR, "component": STR, "reproduction_steps": STR,
                             "acceptance_criteria": ARR, "search_terms": ARR, "category": STR}}
    prompt = (f"Bug report:\n{case.bug_report}\n\nLayer: {case.layer}. Turn this into a precise issue spec. "
              "Look around the code briefly to name the affected component. acceptance_criteria must be "
              "concrete, checkable statements that come from the bug report itself. Don't invent new "
              "requirements or edge-case decisions the report doesn't ask for. Add one final criterion: "
              "all behavior the report doesn't mention stays exactly as it is today.")
    return run_agent(ctx, "triage", BASE + " Your job: triage a bug report into a structured spec.",
                     prompt, pick("list_files", "search_code", "read_source"), schema, max_turns=6)


# ---------- 2. reproduce ----------

def reproduce_core(ctx: RunContext, spec: dict, feedback: str = "") -> dict:
    schema = {"type": "object", "required": ["reproduced", "test_files", "evidence"],
              "properties": {"reproduced": {"type": "boolean"}, "test_files": ARR, "evidence": STR,
                             "missing_info": STR}}
    prompt = (f"Issue spec:\n{_j(spec)}\n\nWrite a small vitest test with write_repro_test that encodes the "
              "expected behavior, so it FAILS on the current code because of this bug, then run it with "
              "run_tests. Import from '../../src/<module>' (tests live in packages/core/test/mobileforge/). "
              "Assert the expected behavior, not the buggy one. If you cannot reproduce it, set "
              "reproduced=false and say what information is missing instead of inventing a cause."
              + (f"\n\nYour last attempt was rejected: {feedback}" if feedback else ""))
    return run_agent(ctx, "reproduce", BASE + " Your job: reproduce the bug with a failing test.",
                     prompt, pick("list_files", "search_code", "read_source", "write_repro_test", "run_tests"),
                     schema, max_turns=10)


# ---------- 3. diagnose ----------

def diagnose(ctx: RunContext, spec: dict, evidence: str, memory_hits: str) -> dict:
    schema = {"type": "object", "required": ["root_cause", "evidence", "confidence", "files", "suggested_fix"],
              "properties": {"root_cause": STR, "evidence": STR, "files": ARR, "suggested_fix": STR,
                             "confidence": {"type": "string", "enum": ["low", "medium", "high"]}}}
    tools = ["list_files", "search_code", "read_source", "run_tests"]
    if ctx.ws.case.layer == "android":
        tools.append("read_logcat")
    if ctx.memory is not None:
        tools.append("retrieve_fix_memory")
    prompt = (f"Issue spec:\n{_j(spec)}\n\nReproduction evidence:\n{evidence[:6000]}\n\n"
              + (f"Similar verified fixes from memory (may or may not apply):\n{memory_hits}\n\n" if memory_hits else "")
              + "Find the root cause. Follow imports and read the actual code. Propose the smallest fix.")
    return run_agent(ctx, "diagnose", BASE + " Your job: find the root cause. You cannot edit files.",
                     prompt, pick(*tools), schema, max_turns=12)


# ---------- 4. repair ----------

def repair(ctx: RunContext, spec: dict, diagnosis: dict, feedback: str) -> dict:
    schema = {"type": "object", "required": ["summary", "rationale"],
              "properties": {"summary": STR, "rationale": STR}}
    editable = ctx.ws.layer["editable"]
    tools = ["read_source", "search_code", "replace_in_file", "git_diff"]
    tools += ["run_tests", "run_typecheck"] if ctx.ws.case.layer == "core" else ["run_maestro"]
    prompt = (f"Issue spec:\n{_j(spec)}\n\nDiagnosis:\n{_j(diagnosis)}\n\n"
              f"Make the smallest correct change. You may only edit files under {editable}. "
              "Don't change behavior the bug report doesn't mention. Run the tests and the typecheck before you submit."
              + (f"\n\nYour previous attempt failed verification. Evidence:\n{feedback[:6000]}" if feedback else ""))
    ctx.edit_budget = 8
    try:
        return run_agent(ctx, "repair", BASE + " Your job: write the fix.", prompt, pick(*tools),
                         schema, max_turns=14)
    finally:
        ctx.edit_budget = None


# ---------- 5. review ----------

def review(ctx: RunContext, spec: dict, diff: str, checks: dict) -> dict:
    issue = {"type": "object", "required": ["file", "problem", "why_it_breaks"],
             "properties": {"file": STR, "problem": STR, "why_it_breaks": STR}}
    schema = {"type": "object", "required": ["blocking_issues", "notes"],
              "properties": {"blocking_issues": {"type": "array", "items": issue}, "notes": ARR}}
    prompt = (f"Bug report:\n{ctx.ws.case.bug_report}\n\nAcceptance criteria:\n{_j(spec.get('acceptance_criteria'))}\n\n"
              f"Patch:\n{diff[:8000]}\n\nDeterministic check results (already passed):\n{_j(checks)}\n\n"
              "List a blocking issue ONLY for a concrete defect you can point to in the code: the patch doesn't fix "
              "the reported behavior, it breaks other behavior, it special-cases test inputs instead of fixing the "
              "logic, or it changes unrelated code. Each blocking issue needs the file, the problem, and an input "
              "that would now behave wrongly. Style, naming, missing comments, missing extra tests, or a different "
              "fix you'd prefer are NOT blocking: put them in notes. Read the source before you claim a defect. "
              "An empty blocking_issues list approves the patch.")
    return run_agent(ctx, "review", BASE + " Your job: code review. Block only on real, demonstrable defects.",
                     prompt, pick("read_source", "search_code"), schema, max_turns=6)


# ---------- single-agent baseline ----------

def single_agent(ctx: RunContext) -> dict:
    case = ctx.ws.case
    schema = {"type": "object", "required": ["summary", "root_cause"],
              "properties": {"summary": STR, "root_cause": STR}}
    names = ["list_files", "search_code", "read_source", "replace_in_file", "git_diff"]
    names += ["write_repro_test", "run_tests", "run_typecheck"] if case.layer == "core" else ["run_maestro", "read_logcat"]
    prompt = (f"Bug report:\n{case.bug_report}\n\nFix this bug. You may only edit files under "
              f"{ctx.ws.layer['editable']}. Reproduce it first, then fix it, then run the tests and the typecheck. "
              + (f"Approved maestro flows: {case.repro_flows}." if case.repro_flows else ""))
    ctx.edit_budget = 8 * ctx.settings.max_repair_attempts
    try:
        return run_agent(ctx, "single", BASE + " You handle the whole job alone.", prompt,
                         [TOOLS[n] for n in names], schema, max_turns=40)
    finally:
        ctx.edit_budget = None
