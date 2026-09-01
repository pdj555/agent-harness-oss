from __future__ import annotations

from pathlib import Path

from harness.fs import iter_files, read_text
from harness.isolation import git

MARKERS = ("TODO", "FIXME", "XXX", "HACK")
MAX_MARKERS = 12
MAX_TESTS = 40


def scan(root: Path) -> str:
    """Rank leverage from software evidence: tests present, open markers, recent commits."""
    root = root.resolve()
    tests: list[str] = []
    markers: list[str] = []
    for path in iter_files(root):
        rel = path.relative_to(root)
        if rel.name.startswith("test_") and rel.suffix == ".py" and len(tests) < MAX_TESTS:
            tests.append(str(rel))
        if len(markers) >= MAX_MARKERS:
            continue
        text = read_text(path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if any(marker in line for marker in MARKERS):
                markers.append(f"{rel}:{number}:{line.strip()[:100]}")
                if len(markers) >= MAX_MARKERS:
                    break
    log = git(["log", "--oneline", "-8"], root)
    commits = (log.stdout or "").strip() or "(none)"
    parts = [
        "test files: " + (", ".join(tests) if tests else "(none)"),
        "open markers:",
        *(markers or ["(none)"]),
        "recent commits:",
        commits,
    ]
    return "\n".join(parts)
