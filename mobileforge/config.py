"""paths, settings and the .env loader. everything else imports from here."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = ROOT / "benchmark"
CASES_DIR = BENCH_DIR / "cases"
RESULTS_DIR = ROOT / "results"
WORK_DIR = ROOT / "workspace"  # gitignored, holds the fineprint clone and run worktrees
RUNS_DIR = WORK_DIR / "runs"
BASE_REPO = WORK_DIR / "fineprint"
STATE_DB = WORK_DIR / "state.db"
MEMORY_DB = WORK_DIR / "memory.db"

FINEPRINT_URL = "https://github.com/ishan-barot/fineprint.git"

# usd per million tokens (input, output). update these if anthropic changes prices
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.00, 20.00),
}


def load_dotenv(path: Path = ROOT / ".env") -> None:
    # tiny .env reader so you don't have to fight windows env vars
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    model: str
    api_key: str | None
    max_repair_attempts: int
    command_timeout: int
    mobile_build_timeout: int

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        return cls(
            model=os.environ.get("MOBILEFORGE_MODEL", "claude-sonnet-5-5"),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            max_repair_attempts=int(os.environ.get("MOBILEFORGE_MAX_ATTEMPTS", "3")),
            command_timeout=int(os.environ.get("MOBILEFORGE_CMD_TIMEOUT", "300")),
            mobile_build_timeout=int(os.environ.get("MOBILEFORGE_BUILD_TIMEOUT", "1800")),
        )


def fineprint_lock() -> str:
    # the exact fineprint commit every benchmark case is built on
    return (BENCH_DIR / "fineprint.lock").read_text(encoding="utf-8").strip()
