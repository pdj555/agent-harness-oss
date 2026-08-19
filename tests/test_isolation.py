from __future__ import annotations

from pathlib import Path

from harness.isolation import create_stage
from tests.helpers import copy_sample, git_init


def _stage(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    original = (source / "tracker.py").read_text(encoding="utf-8")
    stage = create_stage(source, tmp_path / "stages", "run-1")
    return source, original, stage


def test_worktree_edits_do_not_mutate_source_until_publish(tmp_path: Path):
    source, original, stage = _stage(tmp_path)
    target = stage.root / "tracker.py"
    target.write_text(original.replace('return "low"', 'return "high"', 1), encoding="utf-8")
    assert (source / "tracker.py").read_text(encoding="utf-8") == original
    assert target.read_text(encoding="utf-8") != original


def test_git_status_and_diff_reflect_stage_not_source(tmp_path: Path):
    source, original, stage = _stage(tmp_path)
    (stage.root / "tracker.py").write_text(
        original.replace('return "low"', 'return "high"', 1), encoding="utf-8"
    )
    status = stage.status()
    diff = stage.diff()
    assert "tracker.py" in status or "tracker.py" in diff
    assert 'return "high"' in diff or "tracker.py" in stage.changed_files()
    assert (source / "tracker.py").read_text(encoding="utf-8") == original


def test_publish_applies_verified_delta_to_source(tmp_path: Path):
    source, original, stage = _stage(tmp_path)
    updated = original.replace('return "low"', 'return "high"', 1)
    (stage.root / "tracker.py").write_text(updated, encoding="utf-8")
    stage.publish()
    assert (source / "tracker.py").read_text(encoding="utf-8") == updated
