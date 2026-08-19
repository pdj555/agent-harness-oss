from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = [
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CLAUDE.md",
    "AGENTS.md",
    "docs/architecture.md",
    "docs/security.md",
    "docs/agent-runtime.md",
    "docs/demo.md",
    "harness.example.toml",
    "examples/sample-repo/tracker.py",
    "examples/sample-repo/test_tracker.py",
    "skills/public-boundary/SKILL.md",
    "skills/evidence-gated-completion/SKILL.md",
    "skills/isolated-execution/SKILL.md",
    "harness/app.py",
    "harness/runtime.py",
    "harness/static/app.js",
    "harness/static/index.html",
]


def test_required_files_exist_and_are_not_stubs():
    missing = []
    for rel in REQUIRED:
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size < 80:
            missing.append(rel)
    assert missing == []


def test_agent_docs_encode_operating_rules():
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").lower()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8").lower()
    for text in (claude, agents):
        assert "boundary" in text
        assert "public" in text
        assert "models propose" in text
        assert "software verifies" in text
        assert "inspect" in text
        assert "isolat" in text
