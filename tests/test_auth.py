from __future__ import annotations

from harness.auth import verify_password
from tests.conftest import signup


def test_signup_creates_account_and_sets_session_cookie(client):
    response = client.post(
        "/api/signup", json={"username": "ada", "password": "correct-horse"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "ada"
    assert "password" not in body
    assert "password_hash" not in body
    assert client.cookies.get("harness_session")


def test_duplicate_username_is_rejected(client):
    signup(client, "ada", "correct-horse")
    client.cookies.clear()
    response = client.post(
        "/api/signup", json={"username": "ada", "password": "other-password"}
    )
    assert response.status_code == 409
    assert "username" in response.json()["error"].lower()


def test_short_password_is_rejected(client):
    response = client.post("/api/signup", json={"username": "ada", "password": "short"})
    assert response.status_code == 400
    assert "password" in response.json()["error"].lower()


def test_login_returns_usable_session(client):
    signup(client, "ada", "correct-horse")
    client.cookies.clear()
    response = client.post(
        "/api/login", json={"username": "ada", "password": "correct-horse"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "ada"
    assert client.cookies.get("harness_session")
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["username"] == "ada"


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


def test_password_is_stored_as_one_way_hash(client, app):
    password = "correct-horse"
    signup(client, "ada", password)
    user = app.state.store.get_user_by_username("ada")
    assert user is not None
    assert user.password_hash != password
    assert password not in user.password_hash
    assert user.password_hash.startswith("scrypt$")
    assert verify_password(password, user.password_hash)
    assert not verify_password("wrong-password", user.password_hash)
