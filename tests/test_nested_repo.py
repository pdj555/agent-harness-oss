from __future__ import annotations

from pathlib import Path

from harness.config import Config
from harness.demo import run_demo
from harness.isolation import create_stage
from harness.provider import get_provider
from harness.runtime import execute_run
from harness.store import Store
from tests.helpers import copy_sample, git_init


def test_nested_folder_inside_another_git_repo_is_isolated_as_itself(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "README.md").write_text("parent-readme\n", encoding="utf-8")
    (parent / "only-parent.txt").write_text("parent-only\n", encoding="utf-8")
    git_init(parent)
    nested = copy_sample(parent / "sample-repo")
    stage = create_stage(nested, tmp_path / "stages", "nested")
    assert (stage.root / "tracker.py").is_file()
    assert (stage.root / "test_tracker.py").is_file()
    assert not (stage.root / "only-parent.txt").exists()
    assert stage.source == nested.resolve()


def test_packaged_sample_inside_this_clone_completes_with_its_own_tests(tmp_path: Path):
    sample = Path(__file__).resolve().parent.parent / "examples" / "sample-repo"
    config = Config(
        host="127.0.0.1",
        port=7465,
        workspace_roots=[sample],
        provider_name="deterministic",
        data_dir=tmp_path / "data",
        auto_publish=False,
    )
    store = Store(config.data_dir / "harness.db")
    store.initialize()
    user = store.create_user("ada", "scrypt$not-used$not-used")
    repo = store.list_repos(config.workspace_roots)[0]
    run = store.create_run(user.id, repo.id, "Fix the failing tests and prove it.")
    execute_run(run.id, store=store, config=config, provider=get_provider("deterministic"))
    finished = store.get_run(run.id)
    assert finished is not None
    assert finished.status == "completed"
    output = (finished.verification or {}).get("output", "")
    assert finished.verification and finished.verification["passed"] is True
    assert "test_auth" not in output
    assert "test_runtime" not in output
    assert "4 passed" in output
    original = (sample / "tracker.py").read_text(encoding="utf-8")
    assert 'if impact >= 4 and urgency >= 4:\n        return "low"' in original


def test_stage_inside_parent_git_repo_has_diff_after_edit(tmp_path: Path):
    parent = tmp_path / "clone"
    parent.mkdir()
    (parent / "README.md").write_text("clone\n", encoding="utf-8")
    (parent / ".gitignore").write_text(".harness/\n", encoding="utf-8")
    git_init(parent)
    sample = copy_sample(parent / "examples" / "sample-repo")
    stages_dir = parent / ".harness" / "stages"
    stage = create_stage(sample, stages_dir, "run-inside-parent")
    tracker = stage.root / "tracker.py"
    original = tracker.read_text(encoding="utf-8")
    tracker.write_text(
        original.replace(
            '        return "low"',
            '        return "high"',
            1,
        ),
        encoding="utf-8",
    )
    diff = stage.diff()
    assert "tracker.py" in diff
    assert "tracker.py" in stage.changed_files()
    assert 'return "high"' in diff or stage.status().strip()


def test_demo_data_dir_inside_parent_git_repo_completes_with_visible_diff(tmp_path: Path):
    parent = tmp_path / "clone"
    parent.mkdir()
    (parent / "README.md").write_text("clone\n", encoding="utf-8")
    (parent / ".gitignore").write_text(".harness/\n", encoding="utf-8")
    git_init(parent)
    sample = copy_sample(parent / "examples" / "sample-repo")
    config = Config(
        host="127.0.0.1",
        port=7465,
        workspace_roots=[sample],
        provider_name="deterministic",
        data_dir=parent / ".harness",
        auto_publish=False,
    )
    result = run_demo(config, objective="Fix the failing tests and prove it.")
    assert result.status == "completed"
    assert result.diff
    assert "tracker.py" in result.diff
    assert result.review and result.review["passed"] is True
    assert result.verification and result.verification["passed"] is True
