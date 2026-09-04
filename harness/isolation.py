from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class IsolationError(Exception):
    pass


COPY_SKIP_DIRS = {".git", ".harness", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
COPY_SKIP_FILES = {".env"}
SAFE_ENV_SUFFIXES = {"example", "sample", "template"}
PROJECT_PYTHONS = (Path(".venv") / "bin" / "python", Path("venv") / "bin" / "python")


def stage_home(root: Path) -> Path:
    """A writable HOME for stage subprocesses that lives beside, not inside, the stage.

    Tools and checks used to point HOME at ``<stage>/.home``. Anything a command
    wrote there (pip caches, git config, shell profiles) showed up as an untracked
    change, polluted the review, and could be published. Keeping it a sibling keeps
    the change set equal to what the agent actually edited.
    """
    home = root.parent / f"{root.name}.home"
    home.mkdir(parents=True, exist_ok=True)
    return home


def project_python(source: Path) -> Path | None:
    """The repository's own interpreter when it has a local virtual environment."""
    for rel in PROJECT_PYTHONS:
        candidate = source / rel
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def command_env(home: Path, python: str) -> dict[str, str]:
    """Filtered environment for anything executed inside a stage.

    No provider credentials, no host HOME. The interpreter's bin directory leads
    PATH so ``pytest`` and friends resolve to the same environment as ``python``.
    """
    path = os.environ.get("PATH", "/usr/bin:/bin")
    bin_dir = str(Path(python).parent)
    if bin_dir and bin_dir not in path.split(os.pathsep):
        path = f"{bin_dir}{os.pathsep}{path}"
    return {
        "PATH": path,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


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
    shutil.rmtree(root.parent / f"{root.name}.home", ignore_errors=True)
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
            _assert_symlinks_stay_in_stage(root)
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
    paths = [Path(raw) for raw in listed.stdout.split("\0") if raw]
    for rel in paths:
        _validate_overlay_path(rel)
        if _is_sensitive_env_file(rel):
            raise IsolationError(
                f"refusing to stage credential-like file: {rel}; add it to .gitignore"
            )
    overlay_paths = _source_overlay_paths(source, paths)
    for rel in overlay_paths:
        if _is_sensitive_env_file(rel):
            raise IsolationError(
                f"refusing to stage credential-like file: {rel}; add it to .gitignore"
            )
        _overlay_entry(source / rel, _prepare_overlay_destination(root, rel))


def _validate_overlay_path(rel: Path) -> None:
    if rel.is_absolute() or not rel.parts or any(part in {"", ".", "..", ".git"} for part in rel.parts):
        raise IsolationError(f"refusing invalid working-tree path: {rel}")


def _source_overlay_paths(source: Path, paths: list[Path]) -> list[Path]:
    overlay_paths: set[Path] = set()
    terminal_paths: set[Path] = set()
    for rel in sorted(paths, key=lambda path: path.as_posix()):
        current = source
        parts: list[str] = []
        for part in rel.parts:
            parts.append(part)
            current_rel = Path(*parts)
            if current_rel in terminal_paths:
                break
            current /= part
            overlay_paths.add(current_rel)
            if (
                not os.path.lexists(current)
                or current.is_symlink()
                or not current.is_dir()
            ):
                terminal_paths.add(current_rel)
                break
    return sorted(overlay_paths, key=lambda path: (len(path.parts), path.as_posix()))


def _overlay_entry(source: Path, dest: Path) -> None:
    if not os.path.lexists(source):
        _remove_overlay_entry(dest)
    elif source.is_symlink() or source.is_file():
        _copy_overlay_entry(source, dest)
    elif source.is_dir():
        _ensure_overlay_directory(dest)
    else:
        _remove_overlay_entry(dest)


def _prepare_overlay_destination(root: Path, rel: Path) -> Path:
    current = root
    for part in rel.parts[:-1]:
        current /= part
        if os.path.lexists(current):
            if current.is_symlink() or not current.is_dir():
                _remove_overlay_entry(current)
                current.mkdir()
        else:
            current.mkdir()
    return current / rel.name


def _ensure_overlay_directory(dest: Path) -> None:
    if os.path.lexists(dest) and (dest.is_symlink() or not dest.is_dir()):
        _remove_overlay_entry(dest)
    if not dest.exists():
        dest.mkdir()


def _copy_overlay_entry(source: Path, dest: Path) -> None:
    _remove_overlay_entry(dest)
    shutil.copy2(source, dest, follow_symlinks=False)


def _remove_overlay_entry(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


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

    def home(self) -> Path:
        return stage_home(self.root)

    def python(self) -> str:
        found = project_python(self.source)
        return str(found) if found else sys.executable

    def status(self) -> str:
        result = _git(["status", "--short"], self.root)
        return (result.stdout or "") + (result.stderr or "")

    def diff(self) -> str:
        result = _git(["diff", "--", "."], self.root)
        return result.stdout or ""

    def changed_files(self) -> list[str]:
        """Every path that differs from the last commit, one file per entry.

        Untracked files are listed individually so a new directory publishes its
        contents instead of being skipped as a directory. Renames contribute both
        the new and the old path.
        """
        result = _git(
            ["status", "--porcelain", "--untracked-files=all", "-z", "--", "."],
            self.root,
        )
        entries = (result.stdout or "").split("\0")
        names: list[str] = []
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) < 4:
                continue
            code, name = entry[:2], entry[3:]
            paths = [name]
            if "R" in code or "C" in code:
                if index < len(entries) and entries[index]:
                    paths.append(entries[index])
                index += 1
            for path in paths:
                if path and path not in names:
                    names.append(path)
        return names

    def assert_safe(self) -> None:
        _assert_symlinks_stay_in_stage(self.root)

    def publish(self) -> None:
        self.assert_safe()
        source_root = self.source.resolve()
        for rel in self.changed_files():
            src = self.root / rel
            dest = self.source / rel
            if not os.path.lexists(src):
                if os.path.lexists(dest) and not dest.is_dir():
                    dest.unlink()
                continue
            if src.is_dir() and not src.is_symlink():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                dest.resolve().relative_to(source_root)
            except ValueError as exc:
                raise IsolationError(f"refusing to publish outside the source tree: {rel}") from exc
            if dest.is_symlink():
                dest.unlink()
            shutil.copy2(src, dest, follow_symlinks=False)
