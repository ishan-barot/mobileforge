"""long-term fix memory, kept separate from workflow state.

only verified fixes get in: a benchmark fix that passed the hidden tests, or an ad-hoc fix a
human approved. failed or unverified patches never become trusted examples."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

from .config import MEMORY_DB

WORD = re.compile(r"[a-z][a-z0-9_]+")
STOP = set("the a an and or of to in on for is it its this that with when from be are was as at by "
           "not but if then than so do does should shows show".split())


def tokens(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP and len(w) > 2]


class FixMemory:
    def __init__(self, path: Path = MEMORY_DB):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("""create table if not exists fixes (
            id integer primary key, case_id text, category text, component text, bug_report text,
            root_cause text, diff text, files text, validation text, source text, created real)""")
        self.db.commit()

    def add(self, *, case_id: str, category: str, component: str, bug_report: str, root_cause: str,
            diff: str, files: list[str], validation: dict, source: str) -> int:
        cur = self.db.execute(
            "insert into fixes (case_id, category, component, bug_report, root_cause, diff, files, validation, "
            "source, created) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, category, component, bug_report, root_cause, diff, json.dumps(files),
             json.dumps(validation), source, time.time()))
        self.db.commit()
        return cur.lastrowid

    def all(self) -> list[dict]:
        cols = ["id", "case_id", "category", "component", "bug_report", "root_cause", "diff", "files", "source"]
        rows = self.db.execute(f"select {', '.join(cols)} from fixes").fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def search(self, query: str, category: str | None = None, exclude_case: str | None = None,
               k: int = 3) -> list[dict]:
        """metadata filter plus a small tf-idf score. no embedding service needed."""
        records = [r for r in self.all() if r["case_id"] != exclude_case]
        if not records:
            return []
        docs = [Counter(tokens(f"{r['bug_report']} {r['root_cause']} {r['component']} {r['files']}"))
                for r in records]
        df = Counter(w for d in docs for w in d)
        n = len(docs)
        q = Counter(tokens(query))
        scored = []
        for r, d in zip(records, docs):
            score = sum(qc * d[w] * math.log(1 + n / df[w]) for w, qc in q.items() if w in d)
            score /= math.sqrt(sum(d.values()) or 1)
            if category and r["category"] == category:
                score *= 1.5
            if score > 0:
                scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:k]]
