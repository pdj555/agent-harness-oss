from __future__ import annotations

import pytest
from harness.accounts import create_account
from harness.auth import verify_password
from tests.conftest import signup


def test_http_signup_is_disabled(client):
    response = client.post(
        "/api/signup", json={"username": "ada", "password": "correct-horse"}
    )
    assert response.status_code == 403
    error = response.json()["error"].lower()
    assert "email" in error or "browser" in error
    assert client.get("/api/me").status_code == 401
    assert client.app.state.store.get_user_by_username("ada") is None


def test_operator_account_can_log_in(client, app):
    create_account(app.state.store, "ada", "correct-horse")
    response = client.post(
        "/api/login", json={"username": "ada", "password": "correct-horse"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "ada"
    assert client.cookies.get("harness_session")
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["username"] == "ada"
    assert me.json()["provider"]["name"] == "deterministic"
    assert "password" not in me.json()


def test_duplicate_username_is_rejected(app):
    create_account(app.state.store, "ada", "correct-horse")
    with pytest.raises(ValueError, match="username"):
        create_account(app.state.store, "ada", "other-password")


def test_short_password_is_rejected(app):
    with pytest.raises(ValueError, match="password"):
        create_account(app.state.store, "ada", "short")


def test_login_rejects_wrong_password(client):
    signup(client, "ada", "correct-horse")
    client.cookies.clear()
    response = client.post(
        "/api/login", json={"username": "ada", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert "invalid" in response.json()["error"].lower()
    assert client.get("/api/me").status_code == 401


def test_unauthenticated_access_to_protected_routes_is_denied(client):
    for path in ("/api/me", "/api/repos", "/api/runs"):
        response = client.get(path)
        assert response.status_code == 401, path
        body = response.json()
        assert "authentication required" in body["error"].lower()
        assert "username" not in body
        assert "repos" not in body
        assert "runs" not in body


def test_logout_invalidates_session_and_hides_protected_data(client):
    signup(client, "ada", "correct-horse")
    assert client.get("/api/me").status_code == 200
    response = client.post("/api/logout")
    assert response.status_code == 200
    denied = client.get("/api/me")
    assert denied.status_code == 401
    body = denied.json()
    assert "authentication required" in body["error"].lower()
    assert "username" not in body
    assert denied.json() != {"username": "ada"}


def test_password_is_stored_as_one_way_hash(app):
    password = "correct-horse"
    create_account(app.state.store, "ada", password)
    user = app.state.store.get_user_by_username("ada")
    assert user is not None
    assert user.password_hash != password
    assert password not in user.password_hash
    assert user.password_hash.startswith("scrypt$")
    assert verify_password(password, user.password_hash)
    assert not verify_password("wrong-password", user.password_hash)
