from __future__ import annotations

from pathlib import Path

from harness.isolation import create_stage
from harness.verification import run_checks
from tests.helpers import copy_sample, git_init


def test_failing_fixture_does_not_pass_verification(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "run-v")
    result = run_checks(stage.root)
    assert result.passed is False
    assert result.exit_code != 0
    assert result.output
    assert "test" in result.command.lower() or "pytest" in result.command.lower()


def test_model_text_is_not_an_argument_to_verification(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "run-v2")
    result = run_checks(stage.root)
    assert not hasattr(result, "model_claim")
    assert result.passed is False


def test_real_fix_makes_verification_pass(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "run-v3")
    path = stage.root / "tracker.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('return "low"', 'return "high"', 1).replace(
            'return "high"', 'return "low"'
        ),
        encoding="utf-8",
    )
    # The naive double-replace above can swap both; write the correct function instead.
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
    result = run_checks(stage.root)
    assert result.passed is True
    assert result.exit_code == 0
