from __future__ import annotations

from pathlib import Path

from harness.config import (
    add_extra_root,
    has_live_key,
    load_config,
    load_extra_roots,
    redact,
    secret_values,
)
from harness.provider import live_endpoint


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


def test_any_credential_shaped_variable_is_redacted(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-secret-value-123")
    monkeypatch.setenv("VENDOR_ACCESS_TOKEN", "token-secret-value-456")
    monkeypatch.setenv("HARNESS_MODEL", "gpt-oss:20b")

    cleaned = redact(
        "key=ollama-secret-value-123 token=token-secret-value-456 model=gpt-oss:20b"
    )

    assert "ollama-secret-value-123" not in cleaned
    assert "token-secret-value-456" not in cleaned
    assert "gpt-oss:20b" in cleaned


def test_short_values_are_not_treated_as_secrets(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "short")

    assert "short" not in secret_values()


def test_operator_config_declares_the_check_command_and_timeouts(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HARNESS_PROVIDER", "deterministic")
    (tmp_path / "harness.toml").write_text(
        "\n".join(
            [
                "[workspace]",
                'roots = ["."]',
                "",
                "[verification]",
                'command = ["npm", "test"]',
                "timeout = 900",
                "shell_timeout = 240",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(tmp_path / "harness.toml")

    assert config.check_command == ["npm", "test"]
    assert config.check_timeout == 900
    assert config.shell_timeout == 240


def test_the_check_command_defaults_to_pytest(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HARNESS_PROVIDER", "deterministic")

    config = load_config(tmp_path / "missing.toml")

    assert config.check_command == []
    assert config.check_timeout == 300
