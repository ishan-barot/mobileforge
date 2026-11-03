"""per-run context passed to every agent and tool, plus the trace log."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .llm import Provider, Usage


class RunContext:
    def __init__(self, run_id: str, run_dir: Path, ws, llm: Provider, settings, state: dict,
                 memory=None, usage: Usage | None = None):
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.ws = ws
        self.llm = llm
        self.settings = settings
        self.state = state
        self.memory = memory
        self.usage = usage or Usage.from_dict(state.get("usage"))
        self.edit_budget: int | None = None
        self.case_id_for_memory = state.get("case", {}).get("id")
        self._counter = 0
        self.trace_path = self.run_dir / "trace.jsonl"

    def next_id(self) -> int:
        self._counter += 1
        return self._counter

    def log(self, kind: str, agent: str, **data) -> None:
        event = {"t": round(time.time(), 2), "kind": kind, "agent": agent, **data}
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
        if kind == "tool":
            self.state["tool_calls"] = self.state.get("tool_calls", 0) + 1

    def sync_usage(self) -> None:
        self.state["usage"] = self.usage.to_dict()
        self.state["cost_usd"] = self.usage.cost(self.llm.model)


def read_trace(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
