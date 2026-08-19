from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class IsolationError(Exception):
    pass


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(cwd),
    }
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _is_git_root(path: Path) -> bool:
    probe = _git(["rev-parse", "--show-toplevel"], path)
    if probe.returncode != 0:
        return False
    top = Path(probe.stdout.strip()).resolve()
    return top == path.resolve()


def ensure_git_repo(path: Path) -> None:
    probe = _git(["rev-parse", "--is-inside-work-tree"], path)
    if probe.returncode == 0:
        return
    init = _git(["init"], path)
    if init.returncode != 0:
        raise IsolationError(init.stderr.strip() or "git init failed")
    _git(["add", "-A"], path)
    commit = _git(
        [
            "-c",
            "user.email=harness@localhost",
            "-c",
            "user.name=Harness",
            "commit",
            "-m",
            "initial",
        ],
        path,
    )
    if commit.returncode != 0:
        raise IsolationError(commit.stderr.strip() or "git commit failed")


def create_stage(source: Path, stages_dir: Path, run_id: str) -> Stage:
    source = source.resolve()
    if not source.is_dir():
        raise IsolationError("repository path does not exist")
    stages_dir.mkdir(parents=True, exist_ok=True)
    root = (stages_dir / run_id).resolve()
    if root.exists():
        shutil.rmtree(root)
    if _is_git_root(source):
        added = _git(["worktree", "add", "--detach", str(root)], source)
        if added.returncode != 0:
            raise IsolationError(added.stderr.strip() or "git worktree add failed")
        _overlay_working_tree(source, root)
        return Stage(id=run_id, source=source, root=root)
    shutil.copytree(
        source,
        root,
        ignore=shutil.ignore_patterns(".harness", "__pycache__", ".pytest_cache", ".git"),
    )
    ensure_git_repo(root)
    return Stage(id=run_id, source=source, root=root)


def _overlay_working_tree(source: Path, root: Path) -> None:
    skip = {".git", ".harness", "__pycache__", ".pytest_cache"}
    for path in source.rglob("*"):
        if any(part in skip for part in path.parts):
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)


@dataclass
class Stage:
    id: str
    source: Path
    root: Path

    def status(self) -> str:
        result = _git(["status", "--short"], self.root)
        return (result.stdout or "") + (result.stderr or "")

    def diff(self) -> str:
        result = _git(["diff", "--", "."], self.root)
        return result.stdout or ""

    def changed_files(self) -> list[str]:
        result = _git(["diff", "--name-only", "--", "."], self.root)
        names = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        porcelain = _git(["status", "--short"], self.root)
        for line in (porcelain.stdout or "").splitlines():
            name = line[3:].strip()
            if name and name not in names:
                names.append(name)
        return names

    def publish(self) -> None:
        for rel in self.changed_files():
            src = self.root / rel
            dest = self.source / rel
            if not src.exists():
                if dest.exists():
                    dest.unlink()
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest = dest.resolve()
            try:
                dest.relative_to(self.source.resolve())
            except ValueError as exc:
                raise IsolationError(f"refusing to publish outside the source tree: {rel}") from exc
            if src.is_file():
                shutil.copy2(src, dest)
