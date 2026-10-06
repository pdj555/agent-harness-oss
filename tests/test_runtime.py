from __future__ import annotations

from pathlib import Path

import pytest
from harness.config import Config
from harness.provider import Completion, DeterministicProvider, ScriptedProvider, ToolCall
from harness.runtime import _redact, execute_run
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


def test_runtime_redacts_ollama_cloud_key(monkeypatch):
    secret = "ollama-cloud-secret-value"
    monkeypatch.setenv("OLLAMA_API_KEY", secret)

    redacted = _redact(f"tool output contained {secret}")

    assert secret not in redacted
    assert "[redacted]" in redacted


def _symlink_or_skip(link: Path, target: Path | str) -> None:
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")


def test_model_question_does_not_edit_the_repository(tmp_path: Path):
    store, config, _ = _setup(tmp_path)
    source = config.workspace_roots[0]
    before = (source / "tracker.py").read_text(encoding="utf-8")
    repo = store.list_repos(config.workspace_roots)[0]
    user = store.get_user_by_username("ada")
    run = store.create_run(user.id, repo.id, "what model is this?")
    execute_run(run.id, store=store, config=config, provider=DeterministicProvider())
    finished = store.get_run(run.id)
    assert finished.status == "completed"
    assert "deterministic" in (finished.result or "").lower()
    assert "live model" in (finished.result or "").lower() or "scripted" in (finished.result or "").lower()
    assert not finished.files_changed
    assert (source / "tracker.py").read_text(encoding="utf-8") == before


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


def test_unsafe_stage_fails_before_verification_review_or_publish(tmp_path: Path, monkeypatch):
    store, config, run_id = _setup(tmp_path)
    config.auto_publish = True
    source = config.workspace_roots[0]
    original = (source / "tracker.py").read_text(encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside target\n", encoding="utf-8")
    probe = tmp_path / "symlink-probe"
    _symlink_or_skip(probe, outside)
    probe.unlink()
    command = (
        "python3 -c \"from pathlib import Path; target = Path('tracker.py'); "
        f"target.unlink(); target.symlink_to({str(outside)!r})\""
    )
    provider = ScriptedProvider(
        [
            Completion(tool_calls=[ToolCall(name="run_shell", arguments={"command": command})]),
            Completion(text="do not verify"),
        ]
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsafe stages must not enter this pipeline step")

    monkeypatch.setattr("harness.runtime.run_checks", forbidden)
    monkeypatch.setattr("harness.runtime.run_review", forbidden)
    execute_run(run_id, store=store, config=config, provider=provider)

    run = store.get_run(run_id)
    assert run.status == "failed"
    assert run.verification is None
    assert run.review is None
    assert run.stage_path is None
    assert "unsafe stage" in run.blockers
    assert any("Stage safety check failed" in event["detail"] for event in run.events)
    assert (source / "tracker.py").read_text(encoding="utf-8") == original
    assert outside.read_text(encoding="utf-8") == "outside target\n"


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


def test_green_pytest_without_implementation_change_is_not_completion(tmp_path: Path):
    store, config, run_id = _setup(tmp_path)
    original_tests = (config.workspace_roots[0] / "test_tracker.py").read_text(encoding="utf-8")
    provider = ScriptedProvider(
        [
            Completion(
                tool_calls=[
                    ToolCall(
                        name="edit_file",
                        arguments={
                            "path": "test_tracker.py",
                            "old": original_tests,
                            "new": "def test_ok():\n    assert True\n",
                        },
                    )
                ]
            ),
            Completion(text="done: tests pass"),
        ]
    )
    execute_run(run_id, store=store, config=config, provider=provider)
    run = store.get_run(run_id)
    assert run.verification is not None
    assert run.verification["passed"] is True
    assert run.review is not None
    assert run.review["passed"] is False
    assert run.review["passed"] is not run.verification["passed"]
    assert run.status == "failed"


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


def test_internal_error_fails_the_run_instead_of_leaving_it_running(tmp_path: Path, monkeypatch):
    store, config, run_id = _setup(tmp_path)

    def explode(*args, **kwargs):
        raise RuntimeError("disk vanished")

    monkeypatch.setattr("harness.runtime.run_checks", explode)
    provider = ScriptedProvider([Completion(text="done")])
    execute_run(run_id, store=store, config=config, provider=provider)
    run = store.get_run(run_id)
    assert run.status == "failed"
    assert "disk vanished" in (run.result or "")
    assert "internal error" in run.blockers


@pytest.mark.parametrize("phase", ["checks", "review"])
def test_stage_change_during_checks_or_review_prevents_completion(tmp_path: Path, monkeypatch, phase):
    import harness.runtime as runtime

    store, config, run_id = _setup(tmp_path)
    config.auto_publish = True
    source = config.workspace_roots[0]
    original = (source / "tracker.py").read_bytes()
    if phase == "checks":
        checks = runtime.run_checks

        def changed_checks(root, **kwargs):
            evidence = checks(root, **kwargs)
            assert evidence.passed is True
            (root / "tracker.py").write_bytes(original)
            return evidence

        monkeypatch.setattr(runtime, "run_checks", changed_checks)
    else:
        review = runtime.run_review

        def changed_review(stage, evidence, provider):
            result = review(stage, evidence, provider)
            assert result["passed"] is True
            (stage.root / "tracker.py").write_bytes(original)
            return result

        monkeypatch.setattr(runtime, "run_review", changed_review)

    execute_run(run_id, store=store, config=config, provider=DeterministicProvider())

    run = store.get_run(run_id)
    assert run.status == "failed"
    assert run.verification["passed"] is True  # Preserve the real process result.
    assert any("stage changed" in blocker for blocker in run.blockers)
    assert run.published_at is None
    assert (source / "tracker.py").read_bytes() == original
