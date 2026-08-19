from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from harness.authority import (
    MUTATING_TOOLS,
    PathDenied,
    PermissionDenied,
    allow_tool,
    resolve_in_root,
)
from harness.isolation import Stage

SKIP_DIRS = {".git", ".harness", "__pycache__", ".pytest_cache", "node_modules"}


class ToolError(Exception):
    pass


def execute(
    name: str,
    arguments: dict,
    *,
    stage: Stage,
    role: str,
    helper: Callable[[str], str] | None = None,
    stopped: bool = False,
) -> str:
    allow_tool(role, name)
    if stopped and name in MUTATING_TOOLS:
        raise ToolError("stop was requested; mutating work is not allowed")
    args = arguments or {}
    if name == "list_files":
        return _list_files(stage.root, str(args.get("pattern") or "*"))
    if name == "search":
        return _search(stage.root, str(args.get("query") or ""))
    if name == "read_file":
        path = resolve_in_root(stage.root, str(args.get("path") or ""))
        if not path.is_file():
            raise ToolError(f"file not found: {args.get('path')}")
        return path.read_text(encoding="utf-8")
    if name == "edit_file":
        return _edit_file(stage.root, args)
    if name == "run_shell":
        return _run_shell(stage.root, str(args.get("command") or ""))
    if name == "git_status":
        return _git(["status", "--short"], stage.root)
    if name == "git_diff":
        return _git(["diff", "--", "."], stage.root)
    if name == "delegate":
        if helper is None:
            raise ToolError("delegation is unavailable")
        return helper(str(args.get("objective") or ""))
    raise ToolError(f"unknown tool: {name}")


TOOL_PARAMETERS = {
    "list_files": {
        "type": "object",
        "properties": {"pattern": {"type": "string"}},
        "required": ["pattern"],
    },
    "search": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    "read_file": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    "edit_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
        },
        "required": ["path", "old", "new"],
    },
    "run_shell": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    "git_status": {"type": "object", "properties": {}},
    "git_diff": {"type": "object", "properties": {}},
    "delegate": {
        "type": "object",
        "properties": {"objective": {"type": "string"}},
        "required": ["objective"],
    },
}


def tool_specs(role: str) -> list[dict]:
    from harness.authority import ROLE_TOOLS

    descriptions = {
        "list_files": "List files in the isolated worktree matching a glob pattern.",
        "search": "Search file contents for a query string.",
        "read_file": "Read a UTF-8 file relative to the worktree root.",
        "edit_file": "Replace exactly one occurrence of old with new in a file.",
        "run_shell": "Run a command with cwd set to the isolated worktree.",
        "git_status": "Show git status of the isolated worktree.",
        "git_diff": "Show git diff of the isolated worktree.",
        "delegate": "Ask a helper to inspect an independent question and return evidence.",
    }
    specs = []
    for name in sorted(ROLE_TOOLS[role]):
        specs.append(
            {
                "name": name,
                "description": descriptions[name],
                "parameters": TOOL_PARAMETERS[name],
            }
        )
    return specs


def _list_files(root: Path, pattern: str) -> str:
    matches: list[str] = []
    for path in sorted(root.rglob(pattern)):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            matches.append(str(path.relative_to(root)))
    return "\n".join(matches) if matches else "(no files)"


def _search(root: Path, query: str) -> str:
    if not query:
        raise ToolError("search query is required")
    hits: list[str] = []
    needle = query.lower()
    for path in root.rglob("*"):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                hits.append(f"{path.relative_to(root)}:{number}:{line.strip()}")
                if len(hits) >= 50:
                    return "\n".join(hits)
    return "\n".join(hits) if hits else "(no matches)"


def _edit_file(root: Path, args: dict) -> str:
    path = resolve_in_root(root, str(args.get("path") or ""))
    old = args.get("old")
    new = args.get("new")
    if old is None or new is None:
        raise ToolError("edit_file requires old and new")
    if not path.is_file():
        raise ToolError(f"file not found: {args.get('path')}")
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ToolError("old text must match exactly once")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"updated {path.relative_to(root)}"


def _run_shell(root: Path, command: str) -> str:
    if not command.strip():
        raise ToolError("command is required")
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if not parts:
        raise ToolError("command is required")
    if parts[0] in {"python", "python3"}:
        parts[0] = sys.executable
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": str(root / ".home"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    (root / ".home").mkdir(exist_ok=True)
    try:
        proc = subprocess.run(
            parts,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError("command timed out") from exc
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return f"exit {proc.returncode}\n{output}"


def _git(args: list[str], cwd: Path) -> str:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(cwd),
    }
    proc = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def software_helper(objective: str, stage: Stage) -> str:
    listed = execute("list_files", {"pattern": "*"}, stage=stage, role="helper")
    query = next((part for part in objective.replace("/", " ").split() if len(part) > 3), "def")
    try:
        found = execute("search", {"query": query}, stage=stage, role="helper")
    except (ToolError, PathDenied, PermissionDenied):
        found = "(search failed)"
    return f"Helper objective: {objective}\nFiles:\n{listed}\nMatches:\n{found[:3000]}"
