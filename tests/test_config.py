from __future__ import annotations

from pathlib import Path

from harness.config import add_extra_root, has_live_key, load_config, load_extra_roots
from harness.provider import live_endpoint


def test_add_extra_root_is_merged_into_loaded_workspace(tmp_path: Path, monkeypatch):
    repo = tmp_path / "money-repo"
    repo.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HARNESS_PROVIDER", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("HARNESS_API_KEY", raising=False)
    added = add_extra_root(tmp_path / ".harness", repo)
    assert added == repo.resolve()
    assert repo.resolve() in load_extra_roots(tmp_path / ".harness")
    config = load_config(prefer_live=False)
    assert repo.resolve() in [path.resolve() for path in config.workspace_roots]


def test_prefer_live_selects_openai_compat_when_xai_key_present(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.delenv("HARNESS_PROVIDER", raising=False)
    config = load_config(prefer_live=True)
    assert config.provider_name == "openai_compat"
    assert has_live_key()
    key, base, model = live_endpoint()
    assert key == "xai-test-key"
    assert "x.ai" in base
    assert model


def test_demo_path_keeps_deterministic_without_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.delenv("HARNESS_PROVIDER", raising=False)
    config = load_config(prefer_live=False)
    assert config.provider_name == "deterministic"
