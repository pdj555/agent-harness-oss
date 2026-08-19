from __future__ import annotations

import time
from pathlib import Path

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
