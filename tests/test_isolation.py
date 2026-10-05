from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from harness.isolation import IsolationError, create_stage
from tests.helpers import copy_sample, git_init


def _symlink_or_skip(link: Path, target: Path | str) -> None:
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")


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


@pytest.mark.parametrize("git_stage", [False, True])
def test_publish_rejects_escaping_symlink_created_after_stage(tmp_path: Path, git_stage: bool):
    source = copy_sample(tmp_path / "source")
    if git_stage:
        git_init(source)
    original = (source / "tracker.py").read_text(encoding="utf-8")
    stage = create_stage(source, tmp_path / "stages", "run-publish-symlink")
    outside = tmp_path / "outside.txt"
    outside.write_text("must not be published\n", encoding="utf-8")
    target = stage.root / "tracker.py"
    target.unlink()
    _symlink_or_skip(target, outside)

    with pytest.raises(IsolationError, match="symlink escapes"):
        stage.publish()

    assert (source / "tracker.py").read_text(encoding="utf-8") == original
    assert outside.read_text(encoding="utf-8") == "must not be published\n"


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


def test_git_stage_replaces_tracked_directory_with_dirty_file(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    swap = source / "swap"
    swap.mkdir()
    (swap / "old.txt").write_text("old data\n", encoding="utf-8")
    git_init(source)
    shutil.rmtree(swap)
    swap.write_text("replacement data\n", encoding="utf-8")

    stage = create_stage(source, tmp_path / "stages", "run-file-replacement")

    assert (stage.root / "swap").is_file()
    assert (stage.root / "swap").read_text(encoding="utf-8") == "replacement data\n"


def test_git_stage_removes_fully_deleted_tracked_directory(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    removed = source / "removed"
    (removed / "nested").mkdir(parents=True)
    (removed / "old.txt").write_text("old data\n", encoding="utf-8")
    (removed / "nested" / "old.txt").write_text("nested old data\n", encoding="utf-8")
    git_init(source)
    shutil.rmtree(removed)

    stage = create_stage(source, tmp_path / "stages", "run-directory-deletion")

    assert not (stage.root / "removed").exists()


def test_git_stage_rejects_dirty_directory_replacing_tracked_escaping_symlink(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("must not change\n", encoding="utf-8")
    _symlink_or_skip(source / "swap", outside)
    git_init(source)
    (source / "swap").unlink()
    (source / "swap").mkdir()
    (source / "swap" / "untracked.txt").write_text("stage data\n", encoding="utf-8")

    with pytest.raises(IsolationError, match="symlink escapes"):
        create_stage(source, tmp_path / "stages", "run-swap")

    assert sentinel.read_text(encoding="utf-8") == "must not change\n"
    assert not (outside / "untracked.txt").exists()
    assert not (tmp_path / "stages" / "run-swap").exists()


def test_git_stage_replaces_tracked_safe_symlink_with_dirty_directory(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    target = source / "target"
    target.mkdir()
    (target / "keep.txt").write_text("target data\n", encoding="utf-8")
    _symlink_or_skip(source / "swap", "target")
    git_init(source)
    (source / "swap").unlink()
    (source / "swap").mkdir()
    (source / "swap" / "untracked.txt").write_text("stage data\n", encoding="utf-8")

    stage = create_stage(source, tmp_path / "stages", "run-safe-directory")

    assert (stage.root / "swap").is_dir()
    assert not (stage.root / "swap").is_symlink()
    assert (stage.root / "swap" / "untracked.txt").read_text(encoding="utf-8") == "stage data\n"
    assert (stage.root / "target" / "keep.txt").read_text(encoding="utf-8") == "target data\n"


def test_git_stage_replaces_tracked_directory_with_dirty_safe_symlink(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    swap = source / "swap"
    swap.mkdir()
    (swap / "old.txt").write_text("old data\n", encoding="utf-8")
    target = source / "target"
    target.mkdir()
    (target / "keep.txt").write_text("target data\n", encoding="utf-8")
    git_init(source)
    shutil.rmtree(swap)
    _symlink_or_skip(swap, "target")

    stage = create_stage(source, tmp_path / "stages", "run-safe-symlink")

    assert (stage.root / "swap").is_symlink()
    assert (stage.root / "swap").readlink() == Path("target")
    assert (stage.root / "swap" / "keep.txt").read_text(encoding="utf-8") == "target data\n"
    assert not (stage.root / "swap" / "old.txt").exists()


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
    _symlink_or_skip(source / "escape", outside)

    with pytest.raises(IsolationError, match="symlink escapes"):
        create_stage(source, tmp_path / "stages", "run-symlink")

    assert not (tmp_path / "stages" / "run-symlink").exists()


def test_shell_home_lives_beside_the_stage_not_inside_it(tmp_path: Path):
    source, _original, stage = _stage(tmp_path)
    home = stage.home()
    assert home.is_dir()
    assert home.parent == stage.root.parent
    assert stage.root not in home.parents
    (home / ".profile").write_text("written by a tool\n", encoding="utf-8")
    assert stage.changed_files() == []
    assert not (source / ".home").exists()


def test_changed_files_lists_new_files_individually(tmp_path: Path):
    _source, _original, stage = _stage(tmp_path)
    (stage.root / "pkg" / "sub").mkdir(parents=True)
    (stage.root / "pkg" / "sub" / "new.py").write_text("x = 1\n", encoding="utf-8")
    (stage.root / "pkg" / "other.py").write_text("y = 2\n", encoding="utf-8")
    changed = stage.changed_files()
    assert "pkg/sub/new.py" in changed
    assert "pkg/other.py" in changed
    assert "pkg/" not in changed


def test_publish_copies_new_nested_files_and_deletions(tmp_path: Path):
    source, _original, stage = _stage(tmp_path)
    (stage.root / "pkg" / "sub").mkdir(parents=True)
    (stage.root / "pkg" / "sub" / "new.py").write_text("x = 1\n", encoding="utf-8")
    (stage.root / "README.md").unlink()
    stage.publish()
    assert (source / "pkg" / "sub" / "new.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not (source / "README.md").exists()


def test_verified_publish_uses_frozen_files_if_original_changes_during_copy(tmp_path: Path, monkeypatch):
    source, original, stage = _stage(tmp_path)
    updated = original + "\n# checked change\n"
    (stage.root / "tracker.py").write_text(updated, encoding="utf-8")
    digest = stage.content_digest()
    copy = shutil.copy2

    def mutate_original(src, dest, **kwargs):
        if Path(dest) == source / "tracker.py":
            (stage.root / "tracker.py").write_text("unchecked late edit\n", encoding="utf-8")
        return copy(src, dest, **kwargs)

    monkeypatch.setattr("harness.isolation.shutil.copy2", mutate_original)

    stage.publish(expected_digest=digest)

    assert (source / "tracker.py").read_text(encoding="utf-8") == updated
    assert (stage.root / "tracker.py").read_text(encoding="utf-8") == "unchecked late edit\n"
    assert not list(stage.root.parent.glob(".publish-*"))


def test_verified_publish_accepts_nested_additions_and_deletions(tmp_path: Path):
    source, _original, stage = _stage(tmp_path)
    (stage.root / "pkg" / "sub").mkdir(parents=True)
    (stage.root / "pkg" / "sub" / "new.py").write_text("x = 1\n", encoding="utf-8")
    (stage.root / "README.md").unlink()

    stage.publish(expected_digest=stage.content_digest())

    assert (source / "pkg" / "sub" / "new.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not (source / "README.md").exists()
    assert not list(stage.root.parent.glob(".publish-*"))


@pytest.mark.parametrize("change", ["staged-deletion", "staged-rename"])
def test_verified_publish_preserves_staged_deletions_and_renames(tmp_path: Path, change):
    source, _original, stage = _stage(tmp_path)
    readme = (source / "README.md").read_bytes()
    args = ["rm", "README.md"] if change == "staged-deletion" else ["mv", "README.md", "NOTES.md"]
    subprocess.run(["git", *args], cwd=stage.root, check=True, capture_output=True)

    stage.publish(expected_digest=stage.content_digest())

    assert not (source / "README.md").exists()
    if change == "staged-rename":
        assert (source / "NOTES.md").read_bytes() == readme
