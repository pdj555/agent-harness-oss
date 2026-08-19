from __future__ import annotations

from pathlib import Path

import pytest
from harness.authority import PathDenied, resolve_in_root
from tests.conftest import signup


def test_resolve_rejects_parent_escape(tmp_path: Path):
    root = tmp_path / "stage"
    root.mkdir()
    (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(PathDenied):
        resolve_in_root(root, "../secret.txt")


def test_resolve_rejects_absolute_path_outside_root(tmp_path: Path):
    root = tmp_path / "stage"
    root.mkdir()
    with pytest.raises(PathDenied):
        resolve_in_root(root, "/etc/passwd")


def test_resolve_accepts_relative_file_inside_root(tmp_path: Path):
    root = tmp_path / "stage"
    (root / "pkg").mkdir(parents=True)
    target = root / "pkg" / "mod.py"
    target.write_text("ok\n", encoding="utf-8")
    assert resolve_in_root(root, "pkg/mod.py") == target.resolve()


def test_api_rejects_repository_outside_allowlist(client, tmp_path: Path):
    signup(client)
    outsider = tmp_path / "outsider"
    outsider.mkdir()
    response = client.post(
        "/api/runs",
        json={"repo_id": str(outsider), "objective": "do anything"},
    )
    assert response.status_code in {400, 403, 404}
    error = response.json()["error"].lower()
    assert "repo" in error or "not found" in error or "allow" in error


def test_api_does_not_read_arbitrary_filesystem_paths(client):
    signup(client)
    for path in ("/api/files", "/api/fs", "/api/read"):
        response = client.get(path, params={"path": "/etc/passwd"})
        assert response.status_code in {401, 404, 405}


def test_repos_list_contains_only_allowlisted_roots(client, workspace: Path):
    signup(client)
    response = client.get("/api/repos")
    assert response.status_code == 200
    repos = response.json()["repos"]
    assert len(repos) == 1
    assert repos[0]["id"]
    listed = repos[0]["path"]
    assert str(workspace) == listed or workspace.name in listed
    assert "/etc" not in listed
