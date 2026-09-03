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


def test_timeout_is_a_failed_verification_not_a_crash(tmp_path: Path, monkeypatch):
    import subprocess

    source = copy_sample(tmp_path / "source")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "run-timeout")

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"], output="1 test collected")

    monkeypatch.setattr("harness.verification.subprocess.run", hang)
    result = run_checks(stage.root, timeout=7)
    assert result.passed is False
    assert result.exit_code != 0
    assert "timed out after 7s" in result.output
    assert "1 test collected" in result.output


def test_repository_interpreter_runs_the_checks_when_present(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    (source / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    git_init(source)
    fake = source / ".venv" / "bin" / "python"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\necho \"project-venv $*\"\necho \"home=$HOME\"\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    stage = create_stage(source, tmp_path / "stages", "run-venv")
    assert stage.python() == str(fake)
    result = run_checks(stage.root, python=stage.python())
    assert result.passed is True
    assert "project-venv -m pytest -q" in result.output
    assert f"home={stage.home()}" in result.output


def test_harness_interpreter_is_the_fallback(tmp_path: Path):
    import sys

    source = copy_sample(tmp_path / "source")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "run-no-venv")
    assert stage.python() == sys.executable
