"""workflow checkpoints. state is saved after every agent transition so a crashed run
resumes from the last finished step instead of starting over."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .config import STATE_DB


class CheckpointStore:
    def __init__(self, path: Path = STATE_DB):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("""create table if not exists checkpoints (
            run_id text, seq integer, node text, state text, created real,
            primary key (run_id, seq))""")
        self.db.commit()

    def save(self, run_id: str, node: str, state: dict) -> None:
        seq = self.db.execute("select coalesce(max(seq), 0) + 1 from checkpoints where run_id = ?",
                              (run_id,)).fetchone()[0]
        self.db.execute("insert into checkpoints values (?, ?, ?, ?, ?)",
                        (run_id, seq, node, json.dumps(state, default=str), time.time()))
        self.db.commit()

    def latest(self, run_id: str) -> dict | None:
        row = self.db.execute("select state from checkpoints where run_id = ? order by seq desc limit 1",
                              (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def history(self, run_id: str) -> list[tuple[int, str]]:
        return self.db.execute("select seq, node from checkpoints where run_id = ? order by seq",
                               (run_id,)).fetchall()

    def runs(self) -> list[dict]:
        rows = self.db.execute("""select c.state from checkpoints c join (
            select run_id, max(seq) s from checkpoints group by run_id) m
            on c.run_id = m.run_id and c.seq = m.s order by c.created desc""").fetchall()
        return [json.loads(r[0]) for r in rows]
