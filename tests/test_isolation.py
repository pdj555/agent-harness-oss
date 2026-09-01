from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from harness.isolation import IsolationError, create_stage, git
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


def test_git_stage_overlays_working_files_without_copying_ignored_data(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    (source / ".gitignore").write_text(".env\nnode_modules/\n", encoding="utf-8")
    git_init(source)
    (source / "tracker.py").write_text("dirty tracked file\n", encoding="utf-8")
    (source / "notes.txt").write_text("useful untracked file\n", encoding="utf-8")
    (source / ".env").write_text("API_KEY=must-not-enter-stage\n", encoding="utf-8")
    dependency = source / "node_modules" / "package" / "index.js"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("ignored dependency\n", encoding="utf-8")

    stage = create_stage(source, tmp_path / "stages", "run-overlay")

    assert (stage.root / "tracker.py").read_text(encoding="utf-8") == "dirty tracked file\n"
    assert (stage.root / "notes.txt").read_text(encoding="utf-8") == "useful untracked file\n"
    assert not (stage.root / ".env").exists()
    assert not (stage.root / "node_modules").exists()


def test_git_stage_preserves_a_working_tree_deletion(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    (source / "README.md").unlink()

    stage = create_stage(source, tmp_path / "stages", "run-deletion")

    assert not (stage.root / "README.md").exists()
    assert "README.md" in stage.changed_files()


def test_non_git_stage_excludes_credentials_and_dependency_trees(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    (source / ".env").write_text("API_KEY=must-not-enter-stage\n", encoding="utf-8")
    dependency = source / ".venv" / "bin" / "python"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("ignored environment\n", encoding="utf-8")

    stage = create_stage(source, tmp_path / "stages", "run-copy")

    assert (stage.root / "tracker.py").is_file()
    assert not (stage.root / ".env").exists()
    assert not (stage.root / ".venv").exists()
    shutil.rmtree(stage.root)


@pytest.mark.parametrize("name", [".env", ".env.local", ".env.production"])
def test_git_stage_rejects_unignored_credential_files(tmp_path: Path, name: str):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    (source / name).write_text("must-not-enter-stage\n", encoding="utf-8")

    with pytest.raises(IsolationError, match="credential-like file"):
        create_stage(source, tmp_path / "stages", "run-sensitive")


def test_git_stage_allows_env_example(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    (source / ".env.example").write_text("API_KEY=\n", encoding="utf-8")

    stage = create_stage(source, tmp_path / "stages", "run-env-example")

    assert (stage.root / ".env.example").read_text(encoding="utf-8") == "API_KEY=\n"


def test_failed_git_stage_is_cleaned_up_for_a_safe_retry(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    git_init(source)
    (source / ".env").write_text("must-not-enter-stage\n", encoding="utf-8")
    stages = tmp_path / "stages"

    with pytest.raises(IsolationError, match="credential-like file"):
        create_stage(source, stages, "run-retry")

    assert not (stages / "run-retry").exists()
    (source / ".gitignore").write_text(".env\n", encoding="utf-8")
    stage = create_stage(source, stages, "run-retry")
    assert (stage.root / "tracker.py").is_file()
    assert not (stage.root / ".env").exists()


@pytest.mark.parametrize("git_stage", [False, True])
def test_stage_rejects_symlinks_that_escape_the_worktree(tmp_path: Path, git_stage: bool):
    source = copy_sample(tmp_path / "source")
    if git_stage:
        git_init(source)
    outside = tmp_path / "outside.txt"
    outside.write_text("must stay outside the stage\n", encoding="utf-8")
    (source / "escape").symlink_to(outside)

    with pytest.raises(IsolationError, match="symlink escapes"):
        create_stage(source, tmp_path / "stages", "run-symlink")

    assert not (tmp_path / "stages" / "run-symlink").exists()


def test_publish_carries_new_files_in_new_directories(tmp_path: Path):
    source, _original, stage = _stage(tmp_path)
    added = stage.root / "pkg" / "helpers.py"
    added.parent.mkdir()
    added.write_text("def helper():\n    return 1\n", encoding="utf-8")

    assert "pkg/helpers.py" in stage.changed_files()
    stage.publish()

    assert (source / "pkg" / "helpers.py").read_text(encoding="utf-8") == "def helper():\n    return 1\n"


def test_publish_applies_a_rename_on_both_sides(tmp_path: Path):
    source, original, stage = _stage(tmp_path)
    git(["mv", "tracker.py", "renamed_tracker.py"], stage.root)

    changed = stage.changed_files()
    assert "tracker.py" in changed
    assert "renamed_tracker.py" in changed

    stage.publish()

    assert not (source / "tracker.py").exists()
    assert (source / "renamed_tracker.py").read_text(encoding="utf-8") == original


def test_publish_handles_paths_containing_spaces(tmp_path: Path):
    source, _original, stage = _stage(tmp_path)
    (stage.root / "release notes.md").write_text("shipped\n", encoding="utf-8")

    assert "release notes.md" in stage.changed_files()
    stage.publish()

    assert (source / "release notes.md").read_text(encoding="utf-8") == "shipped\n"
