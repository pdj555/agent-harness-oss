from __future__ import annotations

from pathlib import Path

from harness.isolation import create_stage
from harness.leverage import scan
from harness.provider import Completion, ScriptedProvider, ToolCall
from harness.runtime import NEXT_DOLLAR, execute_run
from tests.helpers import copy_sample, git_init
from tests.test_runtime import _setup


def test_scan_reports_tests_and_markers(tmp_path: Path):
    source = copy_sample(tmp_path / "source")
    (source / "notes.py").write_text("# TODO: bill the customer\n", encoding="utf-8")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "scan")
    text = scan(stage.root)
    assert "test_tracker.py" in text
    assert "TODO" in text
    assert "bill the customer" in text


def test_set_plan_replaces_the_static_plan(tmp_path: Path):
    store, config, run_id = _setup(tmp_path)
    provider = ScriptedProvider(
        [
            Completion(
                tool_calls=[
                    ToolCall(
                        name="set_plan",
                        arguments={
                            "why": "Failing tests are the shipping block.",
                            "steps": ["Fix the classifier", "Re-run tests"],
                        },
                    )
                ]
            ),
            Completion(text="done"),
        ]
    )
    execute_run(run_id, store=store, config=config, provider=provider)
    run = store.get_run(run_id)
    assert run.plan[:2] == ["Fix the classifier", "Re-run tests"]
    assert "shipping block" in (run.investigating or "")
    assert any("plan" in event["detail"].lower() for event in run.events)


def test_next_dollar_objective_is_shipped_to_the_client(client, app):
    from harness.accounts import create_account

    create_account(app.state.store, "ada", "correct-horse")
    client.post("/api/login", json={"username": "ada", "password": "correct-horse"})
    me = client.get("/api/me").json()
    assert me["mission"] == NEXT_DOLLAR
    html = client.get("/").text
    assert 'id="next-dollar"' in html
