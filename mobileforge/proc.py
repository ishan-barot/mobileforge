"""the only place mobileforge starts processes. no shell, explicit args, hard timeouts."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


class CommandMissing(RuntimeError):
    pass


def which(name: str) -> str | None:
    # on windows this also finds pnpm.cmd, maestro.bat and friends
    return shutil.which(name)


def resolve(name: str) -> str:
    found = which(name)
    if not found:
        raise CommandMissing(f"'{name}' isn't installed or isn't on PATH")
    return found


def run(cmd: list[str], cwd: Path | str, timeout: int = 300, env: dict | None = None) -> tuple[int, str]:
    exe = resolve(cmd[0])
    full_env = {**os.environ, "CI": "1", "FORCE_COLOR": "0", "NO_COLOR": "1", **(env or {})}
    try:
        p = subprocess.run([exe, *cmd[1:]], cwd=str(cwd), env=full_env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
        return p.returncode, ANSI.sub("", out).strip()
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or b"")
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return 124, ANSI.sub("", partial) + f"\n[timed out after {timeout}s]"


def clip(text: str, limit: int = 12000) -> str:
    # keep the head and tail, test failures usually show up at the end
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n... [{len(text) - limit} chars cut] ...\n" + text[-half:]
