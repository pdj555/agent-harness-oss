from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Split so this file is not itself a hit.
FORBIDDEN = (
    "Pal" + "lara",
    "pal" + "lara",
    "capital_" + "thesis",
    "publication_" + "ready",
    "focus-" + "lead",
    "Kimi " + "K2.7",
)
HOME_MARKERS = ("/Us" + "ers/",)
OPERATOR_MAIL = "preston@" + "pal" + "lara" + ".xyz"


def _source_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    files: list[Path] = []
    for line in listed.stdout.splitlines():
        path = ROOT / line
        if path.name == "test_boundary.py":
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".woff", ".woff2", ".pyc"}:
            continue
        files.append(path)
    return files


def test_tree_does_not_contain_private_names():
    hits: list[str] = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        text = text.replace(OPERATOR_MAIL, "")
        for needle in FORBIDDEN:
            if needle in text:
                hits.append(f"{path.relative_to(ROOT)}: {needle}")
    assert hits == []


def test_tree_does_not_embed_personal_home_paths():
    hits: list[str] = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in HOME_MARKERS:
            if marker in text:
                hits.append(str(path.relative_to(ROOT)))
    assert hits == []


def test_git_history_is_not_the_private_repository():
    result = subprocess.run(
        ["git", "log", "--all", "--oneline"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    log = result.stdout.lower()
    assert "focused orchestration" not in log
    assert "capital thesis" not in log
    assert ("pal" + "lara") not in log
