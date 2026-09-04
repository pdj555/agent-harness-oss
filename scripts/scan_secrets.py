#!/usr/bin/env python3
"""Fail if obvious secrets or private markers appear in source or wheel artifacts."""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

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


def _scan_text(label: str, text: str, *, scan_assignments: bool) -> list[str]:
    hits: list[str] = []
    for pattern in ALWAYS:
        if pattern.search(text):
            hits.append(f"{label}: {pattern.pattern}")
    if scan_assignments:
        for pattern in ASSIGNMENTS:
            if pattern.search(text):
                hits.append(f"{label}: {pattern.pattern}")
    return hits


def _sensitive_env_name(name: str) -> bool:
    leaf = PurePosixPath(name).name.lower()
    if leaf == ".env":
        return True
    if not leaf.startswith(".env."):
        return False
    return leaf not in {".env.example", ".env.sample", ".env.template"}


def scan_source() -> list[str]:
    hits: list[str] = []
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits.extend(
            _scan_text(
                str(path.relative_to(ROOT)),
                text,
                scan_assignments="tests" not in path.parts,
            )
        )
    return hits


def scan_wheel(path: Path) -> list[str]:
    hits: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            label = f"{path.name}:{info.filename}"
            if _sensitive_env_name(info.filename):
                hits.append(f"{label}: credential-like environment file")
            try:
                text = archive.read(info).decode("utf-8")
            except UnicodeDecodeError:
                continue
            hits.extend(_scan_text(label, text, scan_assignments=True))
    return hits


def main(argv: list[str] | None = None) -> int:
    paths = [Path(item) for item in (sys.argv[1:] if argv is None else argv)]
    hits: list[str] = []
    if paths:
        for path in paths:
            if path.suffix != ".whl" or not path.is_file():
                hits.append(f"{path}: expected an existing .whl artifact")
                continue
            hits.extend(scan_wheel(path))
    else:
        hits = scan_source()
    if hits:
        print("possible secrets:")
        print("\n".join(hits))
        return 1
    print("secret scan: no matches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
