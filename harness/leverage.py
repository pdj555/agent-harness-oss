from __future__ import annotations

import subprocess
from pathlib import Path

SKIP = {".git", ".harness", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
MARKERS = ("TODO", "FIXME", "XXX", "HACK")


def scan(root: Path) -> str:
    root = root.resolve()
    tests = [
        str(path.relative_to(root))
        for path in sorted(root.rglob("test_*.py"))
        if not any(part in SKIP for part in path.relative_to(root).parts)
    ]
    markers: list[str] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in SKIP for part in rel.parts):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if any(marker in line for marker in MARKERS):
                markers.append(f"{rel}:{number}:{line.strip()[:100]}")
                if len(markers) >= 12:
                    break
        if len(markers) >= 12:
            break
    log = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "log", "--oneline", "-8"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    commits = (log.stdout or "").strip() or "(none)"
    parts = [
        "test files: " + (", ".join(tests) if tests else "(none)"),
        "open markers:",
        *(markers or ["(none)"]),
        "recent commits:",
        commits,
    ]
    return "\n".join(parts)
