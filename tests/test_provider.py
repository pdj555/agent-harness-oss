from __future__ import annotations

from harness.provider import (
    DeterministicProvider,
    OpenAICompatProvider,
    ScriptedProvider,
    get_provider,
    live_endpoint,
    pick_ollama_model,
    reasoning_effort_for,
)
from harness.tools import tool_specs


def test_pick_ollama_model_prefers_local_oss_over_cloud_tags():
    chosen = pick_ollama_model(
        ["kimi-k2.7-code:cloud", "gpt-oss:20b", "minimax-m2.7:cloud"]
    )
    assert chosen == "gpt-oss:20b"


def test_provider_boundary_substitutes_deterministic():
    provider = get_provider("deterministic")
    assert provider.name == "deterministic"
    assert isinstance(provider, DeterministicProvider)


def test_unknown_provider_is_rejected():
    try:
        get_provider("not-a-vendor")
    except ValueError as exc:
        assert "provider" in str(exc).lower()
    else:
        raise AssertionError("unknown provider must be rejected")


def test_openai_compat_payload_uses_function_tools_and_translated_messages(monkeypatch):
    monkeypatch.delenv("HARNESS_REASONING", raising=False)
    tools = tool_specs("principal")
    payload = OpenAICompatProvider.build_payload(
        [
            {"role": "system", "content": "principal"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "1", "name": "read_file", "arguments": {"path": "tracker.py"}}],
            },
            {
                "role": "tool",
                "name": "read_file",
                "tool_call_id": "1",
                "content": "def classify_priority",
            },
        ],
        tools,
        "gpt-4.1-mini",
    )
    assert payload["tools"][0]["type"] == "function"
    parameters = payload["tools"][0]["function"]["parameters"]
    assert parameters.get("properties")
    assistant = payload["messages"][1]
    assert assistant["tool_calls"][0]["type"] == "function"
    assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
    assert payload["messages"][2]["role"] == "tool"
    assert payload["messages"][2]["tool_call_id"] == "1"
    assert "reasoning_effort" not in payload


def test_gpt56_luna_payload_defaults_to_xhigh_reasoning(monkeypatch):
    monkeypatch.delenv("HARNESS_REASONING", raising=False)
    payload = OpenAICompatProvider.build_responses_payload(
        [
            {"role": "system", "content": "principal"},
            {"role": "user", "content": "next dollar"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "1", "name": "read_file", "arguments": {"path": "tracker.py"}}],
            },
            {
                "role": "tool",
                "name": "read_file",
                "tool_call_id": "1",
                "content": "def classify_priority",
            },
        ],
        [
            {
                "name": "list_files",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "gpt-5.6-luna",
    )
    assert payload["model"] == "gpt-5.6-luna"
    assert payload["reasoning"] == {"effort": "xhigh"}
    assert payload["instructions"] == "principal"
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["name"] == "list_files"
    assert payload["input"][1]["type"] == "function_call"
    assert payload["input"][1]["call_id"] == "1"
    assert payload["input"][2]["type"] == "function_call_output"


def test_reasoning_effort_override_and_off(monkeypatch):
    monkeypatch.setenv("HARNESS_REASONING", "medium")
    assert reasoning_effort_for("gpt-5.6-luna") == "medium"
    monkeypatch.setenv("HARNESS_REASONING", "off")
    assert reasoning_effort_for("gpt-5.6-luna") is None
    monkeypatch.delenv("HARNESS_REASONING")
    assert reasoning_effort_for("gpt-oss:20b") is None


def test_openai_pin_skips_local_ollama(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("HARNESS_PROVIDER", "openai")
    monkeypatch.delenv("HARNESS_MODEL", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("HARNESS_API_KEY", raising=False)
    monkeypatch.setattr("harness.provider.ollama_available", lambda: True)
    key, base, model = live_endpoint()
    assert key == "sk-test"
    assert base.endswith("api.openai.com/v1")
    assert model == "gpt-5.6-luna"


def test_ollama_cloud_key_skips_local_ollama(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-cloud-test-key")
    monkeypatch.delenv("HARNESS_PROVIDER", raising=False)
    monkeypatch.delenv("HARNESS_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HARNESS_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr("harness.provider.ollama_available", lambda: True)
    key, base, model = live_endpoint()
    assert key == "ollama-cloud-test-key"
    assert base.endswith("ollama.com/v1")
    assert model == "gpt-oss:120b"
    provider = get_provider("ollama-cloud")
    assert provider.name == "ollama-cloud"


def test_explicit_local_provider_keeps_local_when_cloud_key_present(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-cloud-test-key")
    monkeypatch.setenv("HARNESS_PROVIDER", "ollama")
    monkeypatch.setattr("harness.provider.ollama_available", lambda: True)
    monkeypatch.setattr("harness.provider.ollama_models", lambda: ["gpt-oss:20b"])
    key, base, model = live_endpoint()
    assert key == "ollama"
    assert model == "gpt-oss:20b"
    assert "11434" in base


def test_local_ollama_still_wins_when_openai_key_is_unpinned(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("HARNESS_PROVIDER", raising=False)
    monkeypatch.delenv("HARNESS_MODEL", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("HARNESS_API_KEY", raising=False)
    monkeypatch.setattr("harness.provider.ollama_available", lambda: True)
    monkeypatch.setattr(
        "harness.provider.ollama_models",
        lambda: ["gpt-oss:20b", "kimi-k2.7-code:cloud"],
    )
    key, base, model = live_endpoint()
    assert key == "ollama"
    assert model == "gpt-oss:20b"
    assert "11434" in base


def test_scripted_provider_shares_the_same_complete_contract():
    scripted = ScriptedProvider([])
    result = scripted.complete(messages=[], tools=[])
    assert hasattr(result, "text")
    assert hasattr(result, "tool_calls")
    deterministic = DeterministicProvider()
    result = deterministic.complete(
        messages=[{"role": "user", "content": "fix the tests"}],
        tools=[{"name": "list_files"}],
    )
    assert result.tool_calls or result.text
