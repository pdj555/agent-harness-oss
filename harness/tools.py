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
from harness.fs import iter_files, read_text
from harness.isolation import Stage, git

LIST_LIMIT = 400
SEARCH_LIMIT = 50
LINE_LIMIT = 200
SHELL_TIMEOUT = 60
SHELL_OUTPUT_LIMIT = 20_000


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
    if name == "set_plan":
        steps = args.get("steps") or []
        if not isinstance(steps, list) or not steps:
            raise ToolError("set_plan requires a non-empty steps list")
        return "plan recorded: " + " | ".join(str(step) for step in steps[:12])
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
    "set_plan": {
        "type": "object",
        "properties": {
            "why": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["steps"],
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
        "set_plan": "Replace the live plan with evidence-backed steps before editing.",
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
    for path in iter_files(root):
        rel = path.relative_to(root)
        if not rel.match(pattern):
            continue
        matches.append(str(rel))
        if len(matches) >= LIST_LIMIT:
            matches.append(f"(stopped at {LIST_LIMIT} files; narrow the pattern)")
            break
    return "\n".join(matches) if matches else "(no files)"


def _search(root: Path, query: str) -> str:
    if not query:
        raise ToolError("search query is required")
    hits: list[str] = []
    needle = query.lower()
    truncated = False
    for path in iter_files(root):
        text = read_text(path)
        if text is None:
            continue
        rel = path.relative_to(root)
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                hits.append(f"{rel}:{number}:{line.strip()[:LINE_LIMIT]}")
                if len(hits) >= SEARCH_LIMIT:
                    truncated = True
                    break
        if truncated:
            break
    if not hits:
        return "(no matches)"
    if truncated:
        hits.append(f"(stopped at {SEARCH_LIMIT} matches; narrow the query)")
    return "\n".join(hits)


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
            timeout=SHELL_TIMEOUT,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"command timed out after {SHELL_TIMEOUT}s") from exc
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if len(output) > SHELL_OUTPUT_LIMIT:
        output = output[-SHELL_OUTPUT_LIMIT:]
    return f"exit {proc.returncode}\n{output}"


def _git(args: list[str], cwd: Path) -> str:
    proc = git(args, cwd)
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def software_helper(objective: str, stage: Stage) -> str:
    listed = execute("list_files", {"pattern": "*"}, stage=stage, role="helper")
    query = next((part for part in objective.replace("/", " ").split() if len(part) > 3), "def")
    try:
        found = execute("search", {"query": query}, stage=stage, role="helper")
    except (ToolError, PathDenied, PermissionDenied):
        found = "(search failed)"
    return f"Helper objective: {objective}\nFiles:\n{listed}\nMatches:\n{found[:3000]}"
