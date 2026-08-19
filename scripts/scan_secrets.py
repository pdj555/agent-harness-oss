#!/usr/bin/env python3
"""Fail if obvious secrets or private markers appear in tracked source."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALWAYS = [
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]
ASSIGNMENTS = [
    re.compile(r"(?i)api[_-]?key\s*=\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"(?i)password\s*=\s*['\"][^'\"]{8,}['\"]"),
]


def tracked_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    files = []
    for line in listed.stdout.splitlines():
        path = ROOT / line
        if not path.is_file():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".lock"}:
            continue
        if path.name == "scan_secrets.py":
            continue
        files.append(path)
    return files


def main() -> int:
    hits: list[str] = []
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in ALWAYS:
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT)}: {pattern.pattern}")
        if "tests" in path.parts:
            continue
        for pattern in ASSIGNMENTS:
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT)}: {pattern.pattern}")
    if hits:
        print("possible secrets:")
        print("\n".join(hits))
        return 1
    print("secret scan: no matches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
