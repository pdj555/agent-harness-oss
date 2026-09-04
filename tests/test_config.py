from __future__ import annotations

from pathlib import Path

from harness.config import add_extra_root, has_live_key, load_config, load_extra_roots
from harness.provider import get_provider, live_endpoint


def test_add_extra_root_is_merged_into_loaded_workspace(tmp_path: Path, monkeypatch):
    repo = tmp_path / "money-repo"
    repo.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HARNESS_PROVIDER", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HARNESS_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    added = add_extra_root(tmp_path / ".harness", repo)
    assert added == repo.resolve()
    assert repo.resolve() in load_extra_roots(tmp_path / ".harness")
    config = load_config(prefer_live=False)
    assert repo.resolve() in [path.resolve() for path in config.workspace_roots]


def test_prefer_live_selects_openai_compat_when_xai_key_present(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.delenv("HARNESS_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HARNESS_API_KEY", raising=False)
    monkeypatch.delenv("HARNESS_MODEL", raising=False)
    monkeypatch.setattr("harness.provider.ollama_available", lambda: False)
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


def test_toml_provider_name_pins_xai_with_competing_keys(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "harness.toml"
    config_path.write_text('[provider]\nname = "xai"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HARNESS_PROVIDER", raising=False)
    monkeypatch.delenv("HARNESS_MODEL", raising=False)
    monkeypatch.delenv("HARNESS_API_BASE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-cloud-test-key")
    monkeypatch.setattr("harness.provider.ollama_available", lambda: True)
    requests = []

    def fake_post(url, payload, api_key, *, timeout):
        requests.append((url, payload, api_key, timeout))
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("harness.provider._post_json", fake_post)

    config = load_config(config_path)
    completion = get_provider(config.provider_name).complete(
        [{"role": "user", "content": "inspect"}], []
    )

    assert completion.text == "ok"
    assert len(requests) == 1
    url, payload, api_key, _timeout = requests[0]
    assert "api.x.ai/v1" in url
    assert api_key == "xai-test-key"
    assert payload["model"] == "grok-4.6"


def test_check_command_and_timeout_come_from_workspace_config(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "harness.toml").write_text(
        '[workspace]\nroots = ["."]\ncheck_command = "npm test"\ncheck_timeout = 45\n',
        encoding="utf-8",
    )
    config = load_config(prefer_live=False)
    assert config.check_command == "npm test"
    assert config.check_timeout == 45
    assert load_config(prefer_live=False, path=None).check_command == "npm test"
