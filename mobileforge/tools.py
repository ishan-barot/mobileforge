"""typed tools the agents can call. no raw shell: every tool validates its inputs and only runs
allowlisted commands inside the run's worktree."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from . import android
from .workspace import PathRejected, Workspace


class ToolError(Exception):
    pass


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable

    @property
    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


def obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


S = {"type": "string"}
I = {"type": "integer"}


# ---------- reading ----------

def _list_files(ctx, a):
    ws: Workspace = ctx.ws
    base = ws.resolve(a.get("dir", ""))
    if not base.is_dir():
        raise ToolError(f"{a.get('dir')} isn't a folder")
    out = []
    for p in sorted(base.rglob("*")):
        try:
            ws.resolve(ws.rel(p))
        except PathRejected:
            continue
        if p.is_file():
            out.append(ws.rel(p))
        if len(out) >= 200:
            out.append("... (more files not shown)")
            break
    return "\n".join(out) or "(empty)"


def _search_code(ctx, a):
    ws: Workspace = ctx.ws
    query = a["query"]
    try:
        pattern = re.compile(query, re.IGNORECASE) if a.get("regex") else None
    except re.error as e:
        raise ToolError(f"bad regex: {e}")
    base = ws.resolve(a.get("dir", ""))
    hits = []
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix not in {".ts", ".tsx", ".js", ".json", ".yaml", ".md"}:
            continue
        try:
            ws.resolve(ws.rel(p))
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except (PathRejected, OSError):
            continue
        for n, line in enumerate(lines, 1):
            if (pattern.search(line) if pattern else query.lower() in line.lower()):
                hits.append(f"{ws.rel(p)}:{n}: {line.strip()[:200]}")
                if len(hits) >= 60:
                    return "\n".join(hits) + "\n... (stopped at 60 matches)"
    return "\n".join(hits) or "no matches"


def _read_source(ctx, a):
    ws: Workspace = ctx.ws
    try:
        path = ws.resolve(a["path"])
    except PathRejected as e:
        raise ToolError(str(e))
    if not path.is_file():
        raise ToolError(f"{a['path']} doesn't exist")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(a.get("start", 1)))
    end = min(len(lines), int(a.get("end", start + 299)))
    body = "\n".join(f"{n:4d}  {lines[n - 1]}" for n in range(start, end + 1))
    return f"{a['path']} (lines {start}-{end} of {len(lines)})\n{body}"


def _read_logcat(ctx, a):
    return android.logcat(a.get("grep"), int(a.get("lines", 200)))


def _git_diff(ctx, a):
    return ctx.ws.diff() or "(no changes yet)"


# ---------- writing ----------

def _replace_in_file(ctx, a):
    ws: Workspace = ctx.ws
    rel = a["path"]
    try:
        path = ws.resolve(rel)
    except PathRejected as e:
        raise ToolError(str(e))
    if not ws.can_edit(rel):
        raise ToolError(f"you can only edit files under {ws.layer['editable']}")
    if ctx.edit_budget is not None and ctx.edit_budget <= 0:
        raise ToolError("edit budget used up for this attempt. submit what you have.")
    if not path.exists():
        if a["old"] != "":
            raise ToolError(f"{rel} doesn't exist. pass old as an empty string to create it.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(a["new"], encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
        count = text.count(a["old"]) if a["old"] else 0
        if count == 0:
            raise ToolError("old text not found. read the file again and copy it exactly.")
        if count > 1:
            raise ToolError(f"old text matches {count} places. include more surrounding lines.")
        path.write_text(text.replace(a["old"], a["new"], 1), encoding="utf-8", newline="")
    if ctx.edit_budget is not None:
        ctx.edit_budget -= 1
    ctx.state["app_built_from_current_code"] = False  # the apk on the emulator is stale now
    return f"edited {rel}"


def _write_repro_test(ctx, a):
    ws: Workspace = ctx.ws
    if ws.layer["repro_dir"] is None:
        raise ToolError("this layer reproduces bugs with maestro flows, use run_maestro")
    path = ws.repro_path(a["name"])
    path.write_text(a["content"], encoding="utf-8")
    ctx.state.setdefault("repro_tests", [])
    rel_pkg = path.relative_to(ws.package_dir).as_posix()
    if rel_pkg not in ctx.state["repro_tests"]:
        ctx.state["repro_tests"].append(rel_pkg)
    return f"wrote {ws.rel(path)}. run it with run_tests(files=['{rel_pkg}'])"


# ---------- running ----------

def _run_tests(ctx, a):
    ws: Workspace = ctx.ws
    files = a.get("files") or []
    for f in files:
        if not re.fullmatch(r"test/[\w./-]+\.test\.ts", f) or ".." in f:
            raise ToolError(f"{f} isn't an allowed test path. use paths like test/flags.test.ts")
    if not files:
        files = ws.visible_tests + ctx.state.get("repro_tests", [])
    ok, out = ws.run_tests(files)
    return ("PASSED\n" if ok else "FAILED\n") + out


def _run_typecheck(ctx, a):
    ok, out = ctx.ws.run_typecheck()
    return ("PASSED\n" if ok else "FAILED\n") + out


def _run_maestro(ctx, a):
    ws: Workspace = ctx.ws
    flow_id = a["flow_id"]
    if flow_id not in ws.case.repro_flows:
        raise ToolError(f"flow {flow_id} isn't approved. approved flows: {ws.case.repro_flows}")
    if not ctx.state.get("app_built_from_current_code"):
        ok, out = android.build_and_install(ws.repo, ctx.settings.mobile_build_timeout)
        if not ok:
            raise ToolError(f"build failed:\n{out}")
        ctx.state["app_built_from_current_code"] = True
    android.clear_logcat()
    flow = ws.repo / ws.layer["test_dir"] / f"{flow_id}.yaml"
    debug = ctx.run_dir / "maestro" / f"{flow_id}-{ctx.next_id()}"
    ok, out = android.run_flow(flow, debug)
    shots = [str(p) for p in android.screenshots(debug)]
    ctx.state.setdefault("screenshots", []).extend(shots)
    logs = android.logcat(lines=80)
    return ("PASSED\n" if ok else "FAILED\n") + out + "\n\n--- logcat ---\n" + logs


def _retrieve_fix_memory(ctx, a):
    if ctx.memory is None:
        raise ToolError("memory is turned off for this run")
    hits = ctx.memory.search(a["query"], category=a.get("category"), exclude_case=ctx.case_id_for_memory)
    if not hits:
        return "no similar verified fixes on record"
    return "\n\n".join(
        f"[fix {h['id']}] category={h['category']} component={h['component']}\n"
        f"bug: {h['bug_report'][:300]}\nroot cause: {h['root_cause']}\n"
        f"verified patch:\n{h['diff'][:1500]}" for h in hits)


TOOLS = {
    "list_files": Tool("list_files", "list files under a folder of the repo (relative path, '' for root)",
                       obj({"dir": S}, []), _list_files),
    "search_code": Tool("search_code", "search source files for text (or a regex if regex=true). returns path:line: text",
                        obj({"query": S, "dir": S, "regex": {"type": "boolean"}}, ["query"]), _search_code),
    "read_source": Tool("read_source", "read a file with line numbers. optional start/end line",
                        obj({"path": S, "start": I, "end": I}, ["path"]), _read_source),
    "read_logcat": Tool("read_logcat", "read recent android logs (react native + crashes), optional text filter",
                        obj({"grep": S, "lines": I}, []), _read_logcat),
    "git_diff": Tool("git_diff", "show the current diff of source changes in the worktree", obj({}, []), _git_diff),
    "replace_in_file": Tool("replace_in_file",
                            "replace one exact, unique chunk of text in an editable source file. "
                            "old must match exactly once. pass old='' to create a new file",
                            obj({"path": S, "old": S, "new": S}, ["path", "old", "new"]), _replace_in_file),
    "write_repro_test": Tool("write_repro_test",
                             "write a vitest test that reproduces the bug. imports work from the test folder, "
                             "e.g. import { wasteFlags } from '../../src/flags'. it should FAIL on the current code",
                             obj({"name": S, "content": S}, ["name", "content"]), _write_repro_test),
    "run_tests": Tool("run_tests", "run vitest on specific test files (paths like test/flags.test.ts), "
                                   "or with no files to run the visible suite plus your repro tests",
                      obj({"files": {"type": "array", "items": S}}, []), _run_tests),
    "run_typecheck": Tool("run_typecheck", "run the typescript compiler on the package", obj({}, []), _run_typecheck),
    "run_maestro": Tool("run_maestro", "build the app from the current code if needed, install it on the emulator "
                                       "and run an approved maestro flow by id",
                        obj({"flow_id": S}, ["flow_id"]), _run_maestro),
    "retrieve_fix_memory": Tool("retrieve_fix_memory", "look up previously verified fixes for similar bugs",
                                obj({"query": S, "category": S}, ["query"]), _retrieve_fix_memory),
}


def pick(*names: str) -> list[Tool]:
    return [TOOLS[n] for n in names]
