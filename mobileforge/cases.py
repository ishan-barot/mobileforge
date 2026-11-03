"""benchmark cases and ad-hoc issues share one shape so the agents never know the difference."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import CASES_DIR

# what each layer of fineprint looks like to the agents
LAYERS = {
    "core": {
        "package_dir": "packages/core",
        "test_dir": "packages/core/test",
        "repro_dir": "packages/core/test/mobileforge",
        "editable": ["packages/core/src/"],
        "readable": ["packages/core/", "apps/mobile/src/", "apps/web/"],
    },
    "android": {
        "package_dir": "apps/mobile",
        "test_dir": "apps/mobile/.maestro",
        "repro_dir": None,
        "editable": ["apps/mobile/src/"],
        "readable": ["apps/mobile/", "packages/core/src/"],
    },
}


@dataclass
class Case:
    id: str
    title: str
    layer: str
    category: str
    bug_report: str
    dir: Path | None = None
    break_patch: str | None = None
    hidden_test: str | None = None   # vitest file, core layer
    hidden_flow: str | None = None   # maestro flow, android layer
    repro_flows: list[str] = field(default_factory=list)  # approved maestro flows the agent may run
    base: str | None = None          # commit to start from, None means the lock or HEAD

    @property
    def layer_info(self) -> dict:
        return LAYERS[self.layer]

    @property
    def is_benchmark(self) -> bool:
        return self.dir is not None

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "layer": self.layer, "category": self.category,
                "bug_report": self.bug_report, "dir": str(self.dir) if self.dir else None,
                "break_patch": self.break_patch, "hidden_test": self.hidden_test,
                "hidden_flow": self.hidden_flow, "repro_flows": self.repro_flows, "base": self.base}

    @classmethod
    def from_dict(cls, d: dict) -> "Case":
        d = dict(d)
        d["dir"] = Path(d["dir"]) if d.get("dir") else None
        return cls(**d)


def load_case(case_id: str) -> Case:
    folder = CASES_DIR / case_id
    meta = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    return Case(
        id=meta["id"], title=meta["title"], layer=meta["layer"], category=meta["category"],
        bug_report=meta["bug_report"], dir=folder, break_patch=meta.get("break_patch"),
        hidden_test=meta.get("hidden_test"), hidden_flow=meta.get("hidden_flow"),
        repro_flows=meta.get("repro_flows", []),
    )


def all_cases(layer: str | None = None) -> list[Case]:
    out = []
    for folder in sorted(CASES_DIR.iterdir()):
        if (folder / "case.json").exists():
            c = load_case(folder.name)
            if layer in (None, "all", c.layer):
                out.append(c)
    return out


def adhoc_case(bug_report: str, layer: str, flows: list[str] | None = None) -> Case:
    # a real bug on the current fineprint main branch, no planted defect and no hidden tests
    return Case(id=f"adhoc-{int(time.time())}", title=bug_report[:60], layer=layer, category="adhoc",
                bug_report=bug_report, repro_flows=flows or (["sample-bill"] if layer == "android" else []),
                base="HEAD")
