from __future__ import annotations

import time
from pathlib import Path

import pytest
from harness.runtime import execute_run
from tests.conftest import signup


def test_signup_login_protected_logout_denied(client):
    refused = client.post(
        "/api/signup", json={"username": "ada", "password": "correct-horse"}
    )
    assert refused.status_code == 403
    signup(client, "ada", "correct-horse")
    client.cookies.clear()
    login = client.post(
        "/api/login", json={"username": "ada", "password": "correct-horse"}
    )
    assert login.status_code == 200
    assert login.json()["username"] == "ada"
    protected = client.get("/api/runs")
    assert protected.status_code == 200
    assert "runs" in protected.json()
    client.post("/api/logout")
    denied = client.get("/api/runs")
    assert denied.status_code == 401
    assert "runs" not in denied.json()
    assert "authentication required" in denied.json()["error"].lower()


def test_objective_creates_durable_run_with_progress_surfaces(client, app):
    signup(client)
    repos = client.get("/api/repos").json()["repos"]
    repo_id = repos[0]["id"]
    created = client.post(
        "/api/runs",
        json={
            "repo_id": repo_id,
            "objective": "Find the highest impact reliability problem, fix it, and prove the result.",
        },
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    deadline = time.time() + 60
    run = None
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "stopped"}:
            break
        time.sleep(0.05)
    assert run is not None
    assert run["objective"]
    assert run["status"] == "completed"
    assert run["plan"]
    assert run["events"]
    assert run["files_changed"]
    assert run["verification"]
    assert run["verification"]["passed"] is True
    assert run["verification"]["output"]
    assert run["review"]
    assert run["review"]["role"] == "reviewer"
    assert run["result"]
    stored = app.state.store.get_run(run_id)
    assert stored is not None
    assert stored.status == "completed"
    history = client.get("/api/runs").json()["runs"]
    assert any(item["id"] == run_id for item in history)


def test_stop_endpoint_stops_in_flight_run(tmp_path, workspace):
    import threading

    from fastapi.testclient import TestClient
    from harness.app import create_app
    from harness.config import Config
    from harness.provider import Completion

    started = threading.Event()
    release = threading.Event()

    class HangProvider:
        name = "hang"

        def complete(self, messages, tools):
            started.set()
            release.wait(15)
            return Completion(text="should not finish as completed after stop")

    config = Config(
        host="127.0.0.1",
        port=7465,
        workspace_roots=[workspace],
        provider_name="hang",
        data_dir=tmp_path / "data-stop",
        auto_publish=False,
        provider_instance=HangProvider(),
    )
    with TestClient(create_app(config)) as local:
        signup(local)
        repo_id = local.get("/api/repos").json()["repos"][0]["id"]
        created = local.post(
            "/api/runs",
            json={"repo_id": repo_id, "objective": "Inspect this repository."},
        )
        run_id = created.json()["id"]
        assert started.wait(5)
        stopped = local.post(f"/api/runs/{run_id}/stop")
        assert stopped.status_code == 200
        release.set()
        deadline = time.time() + 30
        run = None
        while time.time() < deadline:
            run = local.get(f"/api/runs/{run_id}").json()
            if run["status"] in {"stopped", "completed", "failed"}:
                break
            time.sleep(0.05)
        assert run is not None
        assert run["status"] == "stopped"


def test_verified_publish_applies_to_allowlisted_repo(client, workspace):
    signup(client)
    repo_id = client.get("/api/repos").json()["repos"][0]["id"]
    created = client.post(
        "/api/runs",
        json={"repo_id": repo_id, "objective": "Fix the failing tests and prove it."},
    )
    run_id = created.json()["id"]
    deadline = time.time() + 60
    run = None
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "stopped"}:
            break
        time.sleep(0.05)
    assert run is not None
    assert run["status"] == "completed"
    assert "stage_path" not in run
    original = (workspace / "tracker.py").read_text(encoding="utf-8")
    assert 'if impact >= 4 and urgency >= 4:\n        return "low"' in original
    published = client.post(f"/api/runs/{run_id}/publish")
    assert published.status_code == 200
    fixed = (workspace / "tracker.py").read_text(encoding="utf-8")
    assert 'if impact >= 4 and urgency >= 4:\n        return "high"' in fixed


def test_index_serves_classic_script_and_workspace_markup(client):
    page = client.get("/")
    assert page.status_code in {200, 302, 401}
    html = client.get("/login")
    assert html.status_code == 200
    text = html.text
    assert "<script src=" in text
    assert "type=\"module\"" not in text


def test_browser_script_has_no_node_globals(app):
    static = Path(__file__).resolve().parent.parent / "harness" / "static" / "app.js"
    source = static.read_text(encoding="utf-8")
    assert "require(" not in source
    assert "module.exports" not in source
    assert "process.env" not in source


def test_history_rows_are_light_and_publish_records_applied(client, workspace):
    signup(client)
    repo_id = client.get("/api/repos").json()["repos"][0]["id"]
    created = client.post(
        "/api/runs",
        json={"repo_id": repo_id, "objective": "Fix the failing tests and prove it."},
    )
    run_id = created.json()["id"]
    deadline = time.time() + 60
    run = None
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "stopped"}:
            break
        time.sleep(0.05)
    assert run and run["status"] == "completed"
    assert run["published_at"] is None
    rows = client.get("/api/runs").json()["runs"]
    row = next(item for item in rows if item["id"] == run_id)
    assert "diff" not in row and "events" not in row
    assert row["status"] == "completed"
    published = client.post(f"/api/runs/{run_id}/publish").json()
    assert published["published_at"]
    assert any("Published" in event["detail"] for event in published["events"])
    rows = client.get("/api/runs").json()["runs"]
    assert next(item for item in rows if item["id"] == run_id)["published_at"]


def test_publish_without_a_stage_is_a_clear_conflict(client, app):
    import shutil

    signup(client)
    repo_id = client.get("/api/repos").json()["repos"][0]["id"]
    created = client.post(
        "/api/runs",
        json={"repo_id": repo_id, "objective": "Fix the failing tests and prove it."},
    )
    run_id = created.json()["id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] in {"completed", "failed", "stopped"}:
            break
        time.sleep(0.05)
    stored = app.state.store.get_run(run_id)
    assert stored.status == "completed"
    shutil.rmtree(stored.stage_path)
    response = client.post(f"/api/runs/{run_id}/publish")
    assert response.status_code == 409
    assert "stage" in response.json()["error"].lower()


@pytest.mark.parametrize(
    "mutation", ["tracked-edit", "new-file", "untracked-edit", "untracked-delete", "delete", "mode"]
)
def test_publish_rejects_stage_changes_after_verification(client, app, workspace, mutation):
    signup(client)
    original = (workspace / "tracker.py").read_bytes()
    if mutation.startswith("untracked-"):
        (workspace / "notes.txt").write_text("checked notes\n", encoding="utf-8")
    store = app.state.store
    user = store.get_user_by_username("ada")
    repo = store.list_repos(app.state.config.workspace_roots)[0]
    run = store.create_run(user.id, repo.id, "Fix the failing tests and prove it.")
    execute_run(run.id, store=store, config=app.state.config, provider=app.state.provider)
    completed = store.get_run(run.id)
    assert completed.status == "completed"
    assert completed.verification["passed"] is True
    stage = Path(completed.stage_path)
    if mutation == "tracked-edit":
        (stage / "tracker.py").write_bytes(original)
    elif mutation == "new-file":
        (stage / "unchecked.txt").write_text("never verified\n", encoding="utf-8")
    elif mutation == "untracked-edit":
        (stage / "notes.txt").write_text("never verified\n", encoding="utf-8")
    elif mutation == "untracked-delete":
        (stage / "notes.txt").unlink()
    elif mutation == "delete":
        (stage / "tracker.py").unlink()
    else:
        (stage / "tracker.py").chmod(0o755)

    response = client.post(f"/api/runs/{run.id}/publish")

    assert response.status_code == 409
    assert "changed since verification" in response.json()["error"]
    assert (workspace / "tracker.py").read_bytes() == original
    assert not (workspace / "unchecked.txt").exists()
    assert store.get_run(run.id).published_at is None
    if mutation.startswith("untracked-"):
        assert (workspace / "notes.txt").read_text(encoding="utf-8") == "checked notes\n"


@pytest.mark.parametrize("missing_gate", ["fingerprint", "review"])
def test_publish_requires_persisted_verification_and_review(client, app, workspace, missing_gate):
    signup(client)
    original = (workspace / "tracker.py").read_bytes()
    store = app.state.store
    user = store.get_user_by_username("ada")
    repo = store.list_repos(app.state.config.workspace_roots)[0]
    run = store.create_run(user.id, repo.id, "Fix the failing tests and prove it.")
    execute_run(run.id, store=store, config=app.state.config, provider=app.state.provider)
    completed = store.get_run(run.id)
    assert completed.status == "completed"
    if missing_gate == "fingerprint":
        verification = dict(completed.verification)
        verification.pop("stage_digest")
        store.update_run(run.id, verification=verification)
    else:
        store.update_run(run.id, review={"passed": False})

    response = client.post(f"/api/runs/{run.id}/publish")

    assert response.status_code == (409 if missing_gate == "fingerprint" else 400)
    assert (workspace / "tracker.py").read_bytes() == original
    assert store.get_run(run.id).published_at is None


def test_verified_stage_can_be_published_after_restart(client, app, workspace):
    from fastapi.testclient import TestClient
    from harness.app import create_app

    signup(client)
    store = app.state.store
    user = store.get_user_by_username("ada")
    repo = store.list_repos(app.state.config.workspace_roots)[0]
    run = store.create_run(user.id, repo.id, "Fix the failing tests and prove it.")
    execute_run(run.id, store=store, config=app.state.config, provider=app.state.provider)
    completed = store.get_run(run.id)
    assert completed.status == "completed"
    checked = (Path(completed.stage_path) / "tracker.py").read_bytes()

    with TestClient(create_app(app.state.config)) as restarted:
        login = restarted.post("/api/login", json={"username": "ada", "password": "correct-horse"})
        assert login.status_code == 200
        response = restarted.post(f"/api/runs/{run.id}/publish")

    assert response.status_code == 200
    assert response.json()["published_at"]
    assert response.json()["verification"]["stage_digest"] == completed.verification["stage_digest"]
    assert (workspace / "tracker.py").read_bytes() == checked
