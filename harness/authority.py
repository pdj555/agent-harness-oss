from __future__ import annotations

from pathlib import Path


class PathDenied(Exception):
    pass


class PermissionDenied(Exception):
    pass


ROLE_TOOLS = {
    "principal": {
        "list_files",
        "search",
        "read_file",
        "edit_file",
        "run_shell",
        "git_status",
        "git_diff",
        "delegate",
    },
    "helper": {
        "list_files",
        "search",
        "read_file",
        "edit_file",
        "run_shell",
        "git_status",
        "git_diff",
    },
    "reviewer": {
        "list_files",
        "search",
        "read_file",
        "git_status",
        "git_diff",
    },
}

MUTATING_TOOLS = {"edit_file", "run_shell", "delegate"}


def resolve_in_root(root: Path, rel: str) -> Path:
    if not rel or rel.strip() != rel:
        raise PathDenied("path is not allowed")
    root = root.resolve()
    raw = Path(rel)
    candidate = raw.resolve() if raw.is_absolute() else (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PathDenied(f"path is outside the workspace: {rel}") from exc
    parts = candidate.relative_to(root).parts
    if ".git" in parts:
        raise PathDenied("direct access to git internals is not allowed")
    return candidate


def allow_tool(role: str, name: str) -> None:
    allowed = ROLE_TOOLS.get(role, set())
    if name not in allowed:
        raise PermissionDenied(f"{role} is not permitted to use {name}")
