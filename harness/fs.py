"""Shared filesystem walking for tools, scanning, and review.

One pruning walk, one text guard. Agents spend most of their steps here, so
directories that never hold reviewable source are never descended into and
binary or oversized files are never decoded.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

SKIP_DIRS = frozenset(
    {
        ".git",
        ".harness",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "node_modules",
    }
)

MAX_TEXT_BYTES = 512_000


def iter_files(root: Path, *, skip_dirs: frozenset[str] = SKIP_DIRS) -> Iterator[Path]:
    """Yield files under root in a stable order without descending into skip_dirs."""
    for directory, names, filenames in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name not in skip_dirs)
        base = Path(directory)
        for name in sorted(filenames):
            yield base / name


def read_text(path: Path, *, max_bytes: int = MAX_TEXT_BYTES) -> str | None:
    """Return UTF-8 text, or None when the file is binary, oversized, or unreadable."""
    try:
        if path.stat().st_size > max_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None
