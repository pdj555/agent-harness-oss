from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from harness.accounts import create_account
from harness.app import create_app
from harness.config import Config
from tests.helpers import copy_sample, git_init


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    repo = copy_sample(tmp_path / "sample-repo")
    git_init(repo)
    return repo


@pytest.fixture
def config(tmp_path: Path, workspace: Path) -> Config:
    return Config(
        host="127.0.0.1",
        port=7465,
        workspace_roots=[workspace],
        provider_name="deterministic",
        data_dir=tmp_path / "data",
        auto_publish=False,
    )


@pytest.fixture
def app(config: Config):
    return create_app(config)


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def signup(client: TestClient, username: str = "ada", password: str = "correct-horse") -> None:
    create_account(client.app.state.store, username, password)
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
