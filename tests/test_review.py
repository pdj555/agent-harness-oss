from __future__ import annotations

from pathlib import Path

from harness.isolation import create_stage
from harness.provider import ScriptedProvider
from harness.review import run_review
from harness.verification import Verification, run_checks
from tests.helpers import copy_sample, git_init


def test_review_rejects_green_checks_when_nothing_changed(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "review-empty")
    green = Verification(
        passed=True,
        command="python -m pytest -q",
        exit_code=0,
        output="4 passed",
    )
    review = run_review(stage, green, ScriptedProvider([]))
    assert green.passed is True
    assert review["role"] == "reviewer"
    assert review["passed"] is False
    assert review["passed"] is not green.passed
    assert review["findings"]


def test_review_rejects_when_only_tests_change(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "review-tests")
    (stage.root / "test_tracker.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    checks = run_checks(stage.root)
    assert checks.passed is True
    review = run_review(stage, checks, ScriptedProvider([]))
    assert review["passed"] is False
    assert any("test" in item.lower() for item in review["findings"])


def test_review_accepts_implementation_change_when_tests_remain(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "review-ok")
    path = stage.root / "tracker.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            """    if impact >= 4 and urgency >= 4:
        return "low"
    if impact >= 3 or urgency >= 3:
        return "medium"
    return "high"
""",
            """    if impact >= 4 and urgency >= 4:
        return "high"
    if impact >= 3 or urgency >= 3:
        return "medium"
    return "low"
""",
        ),
        encoding="utf-8",
    )
    checks = run_checks(stage.root)
    review = run_review(stage, checks, ScriptedProvider([]))
    assert checks.passed is True
    assert review["passed"] is True
    assert review["role"] == "reviewer"
    assert "tracker.py" in review["files_reviewed"]
