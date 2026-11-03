"""android emulator side: build the app from a worktree, install it, drive it with maestro."""

from __future__ import annotations

from pathlib import Path

from . import proc

APP_ID = "com.ishanbarot.fineprint"


def device_ready() -> tuple[bool, str]:
    if not proc.which("adb"):
        return False, "adb isn't on PATH"
    code, out = proc.run(["adb", "devices"], ".", timeout=30)
    devices = [l for l in out.splitlines()[1:] if l.strip().endswith("device")]
    return bool(devices), out


def build_and_install(repo: Path, timeout: int = 1800) -> tuple[bool, str]:
    """release build so the js is bundled into the apk and no metro server is needed."""
    ok, out = device_ready()
    if not ok:
        return False, f"no running emulator found. start one in android studio first.\n{out}"
    code, out = proc.run(["pnpm", "exec", "expo", "run:android", "--variant", "release", "--no-bundler"],
                         repo / "apps" / "mobile", timeout=timeout)
    return code == 0, proc.clip(out, 6000)


def run_flow(flow: Path, debug_dir: Path, timeout: int = 300) -> tuple[bool, str]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    code, out = proc.run(["maestro", "test", str(flow), "--debug-output", str(debug_dir)],
                         flow.parent, timeout=timeout)
    return code == 0, proc.clip(out, 6000)


def logcat(grep: str | None = None, lines: int = 300) -> str:
    code, out = proc.run(["adb", "logcat", "-d", "-t", str(lines * 4), "ReactNativeJS:V", "AndroidRuntime:E", "*:S"],
                         ".", timeout=30)
    rows = out.splitlines()
    if grep:
        rows = [r for r in rows if grep.lower() in r.lower()]
    return "\n".join(rows[-lines:]) or "(no matching log lines)"


def clear_logcat() -> None:
    if proc.which("adb"):
        proc.run(["adb", "logcat", "-c"], ".", timeout=30)


def screenshots(debug_dir: Path) -> list[Path]:
    return sorted(debug_dir.rglob("*.png"))
