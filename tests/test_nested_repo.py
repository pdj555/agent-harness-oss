from __future__ import annotations

from pathlib import Path

from harness.config import Config
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
