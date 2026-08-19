from __future__ import annotations

from pathlib import Path

from harness.config import Config
from harness.demo import run_demo
from tests.helpers import copy_sample, git_init


def test_deterministic_demo_fixes_sample_and_records_evidence(tmp_path: Path):
    source = copy_sample(tmp_path / "sample-repo")
    git_init(source)
    config = Config(
        host="127.0.0.1",
        port=7465,
        workspace_roots=[source],
        provider_name="deterministic",
        data_dir=tmp_path / "data",
        auto_publish=True,
    )
    result = run_demo(config, objective="Fix the failing tests and prove it.")
    assert result.status == "completed"
    assert result.verification and result.verification["passed"] is True
    assert "passed" in result.verification["output"].lower() or result.verification["exit_code"] == 0
    assert result.files_changed
    assert result.review and result.review["role"] == "reviewer"
    assert result.diff
    fixed = (source / "tracker.py").read_text(encoding="utf-8")
    assert "classify_priority" in fixed
    assert 'if impact >= 4 and urgency >= 4:\n        return "high"' in fixed
    assert 'return "low"' in fixed
