from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class IsolationError(Exception):
    pass


COPY_SKIP_DIRS = {".git", ".harness", ".venv", "__pycache__", ".pytest_cache", "node_modules"}
COPY_SKIP_FILES = {".env"}
SAFE_ENV_SUFFIXES = {"example", "sample", "template"}


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
    if _is_git_root(path):
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
    is_git_root = _is_git_root(source)
    if is_git_root:
        _remove_worktree(source, root)
    elif root.exists():
        shutil.rmtree(root)
    if is_git_root:
        added = _git(["worktree", "add", "--detach", str(root)], source)
        if added.returncode != 0:
            raise IsolationError(added.stderr.strip() or "git worktree add failed")
        try:
            _overlay_working_tree(source, root)
            _assert_symlinks_stay_in_stage(root)
        except Exception:
            _remove_worktree(source, root)
            raise
        return Stage(id=run_id, source=source, root=root)
    try:
        shutil.copytree(
            source,
            root,
            ignore=_copy_ignores,
            symlinks=True,
        )
        _assert_symlinks_stay_in_stage(root)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    ensure_git_repo(root)
    return Stage(id=run_id, source=source, root=root)


def _overlay_working_tree(source: Path, root: Path) -> None:
    listed = _git(["ls-files", "--cached", "--others", "--exclude-standard", "-z"], source)
    if listed.returncode != 0:
        raise IsolationError(listed.stderr.strip() or "git ls-files failed")
    for raw in listed.stdout.split("\0"):
        if not raw:
            continue
        rel = Path(raw)
        if _is_sensitive_env_file(rel):
            raise IsolationError(
                f"refusing to stage credential-like file: {rel}; add it to .gitignore"
            )
        path = source / rel
        dest = root / rel
        if not os.path.lexists(path):
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            elif os.path.lexists(dest):
                dest.unlink()
            continue
        if path.is_dir() and not path.is_symlink():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest, follow_symlinks=False)


def _copy_ignores(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in COPY_SKIP_DIRS or name in COPY_SKIP_FILES or _is_sensitive_env_file(Path(name))
    }


def _is_sensitive_env_file(path: Path) -> bool:
    name = path.name.lower()
    if name == ".env":
        return True
    if not name.startswith(".env."):
        return False
    return name.removeprefix(".env.") not in SAFE_ENV_SUFFIXES


def _remove_worktree(source: Path, root: Path) -> None:
    if root.exists():
        _git(["worktree", "remove", "--force", str(root)], source)
    _git(["worktree", "prune"], source)
    if root.exists():
        shutil.rmtree(root)


def _assert_symlinks_stay_in_stage(root: Path) -> None:
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            path.resolve().relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError) as exc:
            relative = path.relative_to(root)
            raise IsolationError(f"stage symlink escapes the worktree: {relative}") from exc


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
