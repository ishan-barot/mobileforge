"""isolated git worktrees for each run, plus every deterministic check the agents rely on.

the llm never decides whether a patch works. this file does, by running real commands."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import proc
from .cases import Case
from .config import BASE_REPO, FINEPRINT_URL, RUNS_DIR, fineprint_lock

GIT_ID = ["-c", "user.name=mobileforge", "-c", "user.email=mobileforge@localhost"]
HIDDEN_NAME = "__mf_hidden__.test.ts"
BLOCKED_PARTS = {"node_modules", ".git", ".expo", "android", "ios", "dist", ".turbo", ".next"}


class PathRejected(ValueError):
    pass


class Runner:
    """the real commands. tests swap this for a fake so they don't need node."""

    def __init__(self, timeout: int = 300, build_timeout: int = 1800):
        self.timeout = timeout
        self.build_timeout = build_timeout

    def install(self, repo: Path, layer: str) -> tuple[int, str]:
        # core cases never touch dependencies, so reuse the base clone's node_modules through a link.
        # that turns a minutes-long install into an instant one. android builds write into
        # node_modules, so they get a real install.
        if layer == "core" and (BASE_REPO / "node_modules").exists():
            if link_dir(BASE_REPO / "node_modules", repo / "node_modules"):
                core_nm = BASE_REPO / "packages" / "core" / "node_modules"
                if core_nm.exists():
                    link_dir(core_nm, repo / "packages" / "core" / "node_modules")
                return 0, "linked node_modules from the base clone"
        return proc.run(["pnpm", "install", "--frozen-lockfile", "--prefer-offline"], repo,
                        timeout=self.build_timeout)

    def vitest(self, package_dir: Path, files: list[str]) -> tuple[int, str]:
        # call vitest's entry file directly so it works no matter where pnpm hoisted the bin
        for folder in [package_dir, *package_dir.parents]:
            entry = folder / "node_modules" / "vitest" / "vitest.mjs"
            if entry.exists():
                return proc.run(["node", str(entry), "run", *files], package_dir, timeout=self.timeout)
        return proc.run(["pnpm", "exec", "vitest", "run", *files], package_dir, timeout=self.timeout)

    def typecheck(self, package_dir: Path) -> tuple[int, str]:
        # same script fineprint's ci runs
        return proc.run(["pnpm", "run", "typecheck"], package_dir, timeout=self.timeout)


class Workspace:
    def __init__(self, repo: Path, case: Case, runner: Runner | None = None):
        self.repo = Path(repo).resolve()
        self.case = case
        self.layer = case.layer_info
        self.runner = runner or Runner()
        self.package_dir = self.repo / self.layer["package_dir"]
        # snapshot the visible regression suite before any agent touches the repo
        test_dir = self.repo / self.layer["test_dir"]
        if case.layer == "core":
            self.visible_tests = sorted(f"test/{p.name}" for p in test_dir.glob("*.test.ts"))
        else:
            self.visible_tests = sorted(p.name for p in test_dir.glob("*.yaml")) if test_dir.exists() else []

    # ---------- path rules ----------

    def resolve(self, rel: str) -> Path:
        rel = rel.replace("\\", "/").lstrip("/")
        target = (self.repo / rel).resolve()
        if target != self.repo and self.repo not in target.parents:
            raise PathRejected(f"{rel} is outside the repo")
        parts = set(target.relative_to(self.repo).parts)
        if parts & BLOCKED_PARTS:
            raise PathRejected(f"{rel} is in a blocked folder")
        if target.name == HIDDEN_NAME:
            raise PathRejected("that file is off limits")
        return target

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.repo).as_posix()

    def can_edit(self, rel: str) -> bool:
        rel = rel.replace("\\", "/").lstrip("/")
        return any(rel.startswith(prefix) for prefix in self.layer["editable"])

    def repro_path(self, name: str) -> Path:
        # repro tests live in their own folder so they can never overwrite the real suite
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_") or "repro"
        folder = self.repo / self.layer["repro_dir"]
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{safe}.test.ts"

    # ---------- deterministic checks ----------

    def run_tests(self, files: list[str]) -> tuple[bool, str]:
        code, out = self.runner.vitest(self.package_dir, files)
        return code == 0, proc.clip(out)

    def run_visible_suite(self) -> tuple[bool, str]:
        if not self.visible_tests:
            return True, "no visible tests"
        return self.run_tests(self.visible_tests)

    def run_typecheck(self) -> tuple[bool, str]:
        # the typecheck judges the product code, not the agents' throwaway repro tests, so park the
        # repro folder outside the repo while tsc runs
        repro = self.repo / self.layer["repro_dir"] if self.layer["repro_dir"] else None
        parked = self.repo.parent / "_repro_parked"
        moved = bool(repro and repro.exists())
        if moved:
            shutil.rmtree(parked, ignore_errors=True)
            shutil.move(str(repro), str(parked))
        try:
            code, out = self.runner.typecheck(self.package_dir)
        finally:
            if moved:
                shutil.move(str(parked), str(repro))
        return code == 0, proc.clip(out, 6000)

    def run_hidden(self) -> tuple[bool, str] | None:
        """acceptance tests the agents never see. copied in, run, deleted."""
        if not (self.case.dir and self.case.hidden_test):
            return None
        src = self.case.dir / self.case.hidden_test
        dest = self.repo / self.layer["test_dir"] / HIDDEN_NAME
        shutil.copyfile(src, dest)
        try:
            return self.run_tests([f"test/{HIDDEN_NAME}"])
        finally:
            dest.unlink(missing_ok=True)

    # ---------- git ----------

    def git(self, *args: str) -> tuple[int, str]:
        return proc.run(["git", *GIT_ID, *args], self.repo, timeout=120)

    def diff(self, include_repro: bool = False) -> str:
        self.git("add", "-A", "-N", ".")  # intent-to-add so new files show up in the diff
        paths = ["--", "."] if include_repro else ["--", ".", f":(exclude){self.layer['repro_dir'] or '__none__'}"]
        return self.git("diff", *paths)[1]

    def changed_files(self) -> list[str]:
        tracked = self.git("diff", "--name-only", "HEAD")[1].splitlines()
        new = self.git("ls-files", "--others", "--exclude-standard")[1].splitlines()
        return sorted({p.strip() for p in tracked + new if p.strip()})

    def source_changes(self) -> list[str]:
        repro = self.layer["repro_dir"] or "__none__"
        return [f for f in self.changed_files() if not f.startswith(repro)]


# ---------- creating and removing worktrees ----------

def link_dir(target: Path, link: Path) -> bool:
    """directory junction on windows (no admin needed), symlink everywhere else."""
    if link.exists():
        return True
    try:
        if os.name == "nt":
            code, _ = proc.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], link.parent, timeout=60)
            return code == 0
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


def unlink_dirs(repo: Path) -> None:
    # remove links first so deleting the worktree never touches the shared node_modules
    for link in (repo / "node_modules", repo / "packages" / "core" / "node_modules"):
        if link.is_symlink():
            link.unlink()
        elif os.name == "nt" and link.exists() and os.path.isjunction(link):
            os.rmdir(link)

def setup_base(log=print) -> Path:
    """clone fineprint once. every run gets a cheap worktree off this clone."""
    BASE_REPO.parent.mkdir(parents=True, exist_ok=True)
    if not (BASE_REPO / ".git").exists():
        log(f"cloning {FINEPRINT_URL} ...")
        code, out = proc.run(["git", "clone", FINEPRINT_URL, str(BASE_REPO)], BASE_REPO.parent, timeout=900)
        if code != 0:
            raise RuntimeError(out)
    else:
        proc.run(["git", "fetch", "--all"], BASE_REPO, timeout=300)
    lock = fineprint_lock()
    code, out = proc.run(["git", "cat-file", "-e", f"{lock}^{{commit}}"], BASE_REPO)
    if code != 0:
        raise RuntimeError(f"pinned fineprint commit {lock} isn't in the clone")
    return BASE_REPO


def create_workspace(case: Case, run_id: str, runner: Runner, log=print) -> Workspace:
    if not (BASE_REPO / ".git").exists():
        raise RuntimeError("run `mobileforge setup` first, the fineprint clone is missing")
    dest = RUNS_DIR / run_id / "repo"
    dest.parent.mkdir(parents=True, exist_ok=True)
    base = case.base or fineprint_lock()
    if base == "HEAD":
        base = proc.run(["git", "rev-parse", "origin/main"], BASE_REPO)[1].strip()

    code, out = proc.run(["git", "worktree", "add", "--detach", str(dest), base], BASE_REPO, timeout=300)
    if code != 0:
        raise RuntimeError(f"git worktree add failed:\n{out}")

    if case.break_patch:
        # plant the known defect, then commit it so the agent's diff only shows its own changes
        patch = (case.dir / case.break_patch).resolve()
        code, out = proc.run(["git", "apply", "--whitespace=nowarn", str(patch)], dest)
        if code != 0:
            raise RuntimeError(f"couldn't apply {patch.name}:\n{out}")
        proc.run(["git", *GIT_ID, "commit", "-qam", "snapshot"], dest)

    log("installing dependencies in the worktree (fast after the first time) ...")
    code, out = runner.install(dest, case.layer)
    if code != 0:
        raise RuntimeError(f"pnpm install failed:\n{proc.clip(out, 4000)}")
    return Workspace(dest, case, runner)


def remove_workspace(run_id: str) -> None:
    dest = RUNS_DIR / run_id / "repo"
    if dest.exists():
        unlink_dirs(dest)
        proc.run(["git", "worktree", "remove", "--force", str(dest)], BASE_REPO, timeout=300)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    proc.run(["git", "worktree", "prune"], BASE_REPO)
