from __future__ import annotations

from pathlib import Path

from harness.config import Config
from harness.provider import Completion, ScriptedProvider, ToolCall
from harness.runtime import execute_run
from harness.store import Store
from tests.helpers import copy_sample, git_init


def _setup(tmp_path: Path) -> tuple[Store, Config, str]:
    source = copy_sample(tmp_path / "sample-repo")
    git_init(source)
    config = Config(
        host="127.0.0.1",
        port=7465,
        workspace_roots=[source],
        provider_name="scripted",
        data_dir=tmp_path / "data",
        auto_publish=False,
    )
    store = Store(config.data_dir / "harness.db")
    store.initialize()
    user = store.create_user("ada", "scrypt$not-used$not-used")
    repo = store.list_repos(config.workspace_roots)[0]
    run = store.create_run(user.id, repo.id, "Find the reliability bug, fix it, and prove it.")
    return store, config, run.id


def test_model_claiming_done_without_a_fix_does_not_complete(tmp_path: Path):
    store, config, run_id = _setup(tmp_path)
    provider = ScriptedProvider([Completion(text="done: VERIFICATION_PASSED")])
    execute_run(run_id, store=store, config=config, provider=provider)
    run = store.get_run(run_id)
    assert run.status == "failed"
    assert run.verification is not None
    assert run.verification["passed"] is False
    assert "done" in (run.result or "").lower() or run.status == "failed"


def test_model_cannot_skip_permission_checks_by_asking(tmp_path: Path):
    store, config, run_id = _setup(tmp_path)
    provider = ScriptedProvider(
        [
            Completion(
                tool_calls=[
                    ToolCall(name="read_file", arguments={"path": "/etc/passwd"}),
                ]
            ),
            Completion(text="done"),
        ]
    )
    execute_run(run_id, store=store, config=config, provider=provider)
    run = store.get_run(run_id)
    blob = " ".join(event["detail"] for event in run.events)
    assert "root:" not in blob
    denied = any(
        "denied" in event["detail"].lower() or "path" in event["detail"].lower()
        for event in run.events
    )
    assert denied


def test_stop_prevents_further_mutating_work(tmp_path: Path):
    store, config, run_id = _setup(tmp_path)

    class StoppingProvider:
        name = "scripted"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                store.request_stop(run_id)
                return Completion(
                    tool_calls=[
                        ToolCall(
                            name="edit_file",
                            arguments={
                                "path": "tracker.py",
                                "old": "Classify",
                                "new": "SHOULD_NOT_APPLY",
                            },
                        )
                    ]
                )
            return Completion(
                tool_calls=[
                    ToolCall(
                        name="edit_file",
                        arguments={
                            "path": "README.md",
                            "old": "Sample",
                            "new": "MUTATED_AFTER_STOP",
                        },
                    )
                ]
            )

    provider = StoppingProvider()
    execute_run(run_id, store=store, config=config, provider=provider)
    run = store.get_run(run_id)
    assert run.status == "stopped"
    source = config.workspace_roots[0]
    # Source must remain untouched. Stage may have at most the in-flight first tool,
    # but no successful mutating work after stop.
    stage_root = Path(run.stage_path) if run.stage_path else None
    if stage_root and stage_root.exists():
        readme = (stage_root / "README.md").read_text(encoding="utf-8")
        assert "MUTATED_AFTER_STOP" not in readme
    assert "MUTATED_AFTER_STOP" not in (source / "README.md").read_text(encoding="utf-8")


def test_independent_review_is_distinct_from_principal_done_text(tmp_path: Path):
    store, config, run_id = _setup(tmp_path)
    provider = ScriptedProvider(
        [
            Completion(
                tool_calls=[
                    ToolCall(
                        name="edit_file",
                        arguments={
                            "path": "tracker.py",
                            "old": (
                                '    if impact >= 4 and urgency >= 4:\n'
                                '        return "low"\n'
                                '    if impact >= 3 or urgency >= 3:\n'
                                '        return "medium"\n'
                                '    return "high"\n'
                            ),
                            "new": (
                                '    if impact >= 4 and urgency >= 4:\n'
                                '        return "high"\n'
                                '    if impact >= 3 or urgency >= 3:\n'
                                '        return "medium"\n'
                                '    return "low"\n'
                            ),
                        },
                    )
                ]
            ),
            Completion(text="I am done. Principal sign-off."),
        ]
    )
    execute_run(run_id, store=store, config=config, provider=provider)
    run = store.get_run(run_id)
    assert run.status == "completed"
    assert run.review is not None
    assert run.review.get("role") == "reviewer"
    assert run.review.get("summary")
    assert "Principal sign-off" not in (run.review.get("summary") or "")
    assert run.verification and run.verification["passed"] is True
    assert run.files_changed


def test_failed_check_is_a_failure_state_not_completion(tmp_path: Path):
    store, config, run_id = _setup(tmp_path)
    provider = ScriptedProvider(
        [
            Completion(
                tool_calls=[
                    ToolCall(
                        name="edit_file",
                        arguments={
                            "path": "tracker.py",
                            "old": 'return "low"',
                            "new": 'return "broken"',
                        },
                    )
                ]
            ),
            Completion(text="done"),
        ]
    )
    execute_run(run_id, store=store, config=config, provider=provider)
    run = store.get_run(run_id)
    assert run.status == "failed"
    assert run.verification is not None
    assert run.verification["passed"] is False
