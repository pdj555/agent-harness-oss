from __future__ import annotations

from harness.provider import DeterministicProvider, OpenAICompatProvider, ScriptedProvider, get_provider
from harness.tools import tool_specs


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


def test_openai_compat_payload_uses_function_tools_and_translated_messages():
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
