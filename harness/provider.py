from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str = "call"


@dataclass
class Completion:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class Provider(Protocol):
    name: str

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion: ...


class ScriptedProvider:
    name = "scripted"

    def __init__(self, script: list[Completion]) -> None:
        self.script = list(script)

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion:
        if not self.script:
            return Completion(text="")
        return self.script.pop(0)


BUGGY_PRIORITY = """    if impact >= 4 and urgency >= 4:
        return "low"
    if impact >= 3 or urgency >= 3:
        return "medium"
    return "high"
"""

FIXED_PRIORITY = """    if impact >= 4 and urgency >= 4:
        return "high"
    if impact >= 3 or urgency >= 3:
        return "medium"
    return "low"
"""


class DeterministicProvider:
    """Replaceable provider used by tests and the local demo.

    It drives the same tools as a live vendor. It does not decide that
    verification passed; the runtime does that in software.
    """

    name = "deterministic"

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion:
        names = {spec["name"] for spec in tools if isinstance(spec, dict) and "name" in spec}
        if "edit_file" not in names:
            return Completion(
                text="Independent review of the isolated diff: no blocking issues in the checked evidence."
            )

        results = _tool_history(messages)
        if not _has_tool(results, "list_files"):
            return _call("list_files", {"pattern": "*.py"})
        if not _has_tool(results, "set_plan"):
            return _call(
                "set_plan",
                {
                    "why": "Failing priority tests block shipping this library.",
                    "steps": [
                        "Confirm the failing priority tests",
                        "Fix classify_priority labels to match the spec",
                        "Re-run tests",
                    ],
                },
            )
        if not _read_path(results, "tracker.py"):
            return _call("read_file", {"path": "tracker.py"})
        if not _read_path(results, "test_tracker.py"):
            return _call("read_file", {"path": "test_tracker.py"})
        if not _has_tool(results, "run_shell"):
            return _call("run_shell", {"command": "python3 -m pytest -q"})

        last_shell = _last_tool(results, "run_shell")
        tests_pass = bool(last_shell and _shell_passed(last_shell["content"]))
        if not tests_pass and not _has_tool(results, "edit_file"):
            tracker = _read_path(results, "tracker.py") or ""
            if BUGGY_PRIORITY in tracker:
                return _call(
                    "edit_file",
                    {"path": "tracker.py", "old": BUGGY_PRIORITY, "new": FIXED_PRIORITY},
                )
            return Completion(text="No safe repair is obvious from the current files.")
        if _has_tool(results, "edit_file") and not tests_pass and _count_tool(results, "run_shell") < 2:
            return _call("run_shell", {"command": "python3 -m pytest -q"})
        if not _has_tool(results, "git_diff"):
            return _call("git_diff", {})
        return Completion(text="The isolated change is ready for software verification.")


REASONING_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max"})


def reasoning_effort_for(model: str) -> str | None:
    """Chat Completions `reasoning_effort`. GPT-5.6 defaults to xhigh."""
    raw = os.environ.get("HARNESS_REASONING")
    if raw is not None:
        value = raw.strip().lower()
        if value in {"", "off"}:
            return None
        return value if value in REASONING_EFFORTS else None
    if model.lower().startswith("gpt-5"):
        return "xhigh"
    return None


class OpenAICompatProvider:
    name = "openai_compat"

    @staticmethod
    def build_payload(messages: list[dict], tools: list[dict], model: str) -> dict:
        payload = {
            "model": model,
            "messages": _openai_messages(messages),
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": spec["name"],
                        "description": spec.get("description", ""),
                        "parameters": spec.get("parameters")
                        or {"type": "object", "properties": {}},
                    },
                }
                for spec in tools
            ],
        }
        effort = reasoning_effort_for(model)
        if effort:
            payload["reasoning_effort"] = effort
        return payload

    @staticmethod
    def build_responses_payload(messages: list[dict], tools: list[dict], model: str) -> dict:
        instructions = ""
        input_items: list[dict] = []
        for message in _openai_messages(messages):
            role = message.get("role")
            if role == "system":
                extra = message.get("content") or ""
                instructions = f"{instructions}\n{extra}".strip() if extra else instructions
            elif role == "assistant" and message.get("tool_calls"):
                if message.get("content"):
                    input_items.append({"role": "assistant", "content": message["content"]})
                for call in message["tool_calls"]:
                    function = call.get("function") or {}
                    input_items.append(
                        {
                            "type": "function_call",
                            "call_id": call.get("id") or "call",
                            "name": function.get("name") or "",
                            "arguments": function.get("arguments") or "{}",
                        }
                    )
            elif role == "tool":
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.get("tool_call_id") or "call",
                        "output": message.get("content") or "",
                    }
                )
            else:
                input_items.append({"role": role, "content": message.get("content") or ""})
        payload = {
            "model": model,
            "input": input_items,
            "tools": [
                {
                    "type": "function",
                    "name": spec["name"],
                    "description": spec.get("description", ""),
                    "parameters": spec.get("parameters")
                    or {"type": "object", "properties": {}},
                    "strict": False,
                }
                for spec in tools
            ],
        }
        if instructions:
            payload["instructions"] = instructions
        effort = reasoning_effort_for(model)
        if effort:
            payload["reasoning"] = {"effort": effort}
        return payload

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion:
        api_key, base, model = live_endpoint()
        if model.lower().startswith("gpt-5") and "openai.com" in base:
            payload = self.build_responses_payload(messages, tools, model)
            body = _post_json(f"{base}/responses", payload, api_key, timeout=600)
            return _completion_from_responses(body)
        payload = self.build_payload(messages, tools, model)
        payload["tool_choice"] = "auto"
        timeout = 600 if payload.get("reasoning_effort") or "ollama.com" in base else 120
        body = _post_json(f"{base}/chat/completions", payload, api_key, timeout=timeout)
        return _completion_from_chat(body)


def _post_json(url: str, payload: dict, api_key: str, *, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"provider request failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"provider request failed: {exc}") from exc


def _completion_from_chat(body: dict) -> Completion:
    message = body["choices"][0]["message"]
    calls = []
    for item in message.get("tool_calls") or []:
        function = item.get("function") or {}
        raw_args = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError:
            arguments = {}
        calls.append(
            ToolCall(
                id=item.get("id") or "call",
                name=function.get("name") or "",
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )
    return Completion(text=message.get("content") or "", tool_calls=calls)


def _completion_from_responses(body: dict) -> Completion:
    calls = []
    for item in body.get("output") or []:
        if item.get("type") != "function_call":
            continue
        raw_args = item.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError:
            arguments = {}
        calls.append(
            ToolCall(
                id=item.get("call_id") or item.get("id") or "call",
                name=item.get("name") or "",
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )
    if calls:
        return Completion(text="", tool_calls=calls)
    return Completion(text=body.get("output_text") or "", tool_calls=[])


def ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def ollama_available() -> bool:
    try:
        with urllib.request.urlopen(ollama_host() + "/api/tags", timeout=0.4) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def ollama_models() -> list[str]:
    try:
        with urllib.request.urlopen(ollama_host() + "/api/tags", timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return []
    return [str(item.get("name")) for item in payload.get("models") or [] if item.get("name")]


def pick_ollama_model(names: list[str]) -> str:
    explicit = os.environ.get("HARNESS_MODEL") or os.environ.get("OLLAMA_MODEL")
    if explicit:
        return explicit
    local = [name for name in names if ":cloud" not in name]
    pool = local or names
    for needle in ("gpt-oss:20b", "qwen2.5-coder", "qwen3-coder", "gpt-oss", "coder"):
        for name in pool:
            if needle in name:
                return name
    return pool[0] if pool else "gpt-oss:20b"


def _openai_key() -> str | None:
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("HARNESS_API_KEY")


def _is_openai_model(model: str | None) -> bool:
    if not model:
        return False
    name = model.lower()
    return name.startswith("gpt-5") or name.startswith("gpt-4")


def live_endpoint() -> tuple[str, str, str]:
    """Return (api_key, base_url, model) for a live vendor."""
    provider = (os.environ.get("HARNESS_PROVIDER") or "").lower()
    explicit_model = os.environ.get("HARNESS_MODEL")
    openai_key = _openai_key()
    openai_base = os.environ.get("HARNESS_API_BASE", "https://api.openai.com/v1").rstrip("/")
    if openai_key and (provider == "openai" or _is_openai_model(explicit_model)):
        return openai_key, openai_base, explicit_model or "gpt-5.6-luna"
    if os.environ.get("OLLAMA_API_KEY") and provider != "ollama":
        return (
            os.environ["OLLAMA_API_KEY"],
            os.environ.get("HARNESS_API_BASE", "https://ollama.com/v1").rstrip("/"),
            explicit_model or "gpt-oss:120b",
        )
    if ollama_available() and provider not in {"openai", "xai", "ollama-cloud"}:
        model = pick_ollama_model(ollama_models())
        return "ollama", ollama_host() + "/v1", model
    if os.environ.get("XAI_API_KEY"):
        return (
            os.environ["XAI_API_KEY"],
            os.environ.get("HARNESS_API_BASE", "https://api.x.ai/v1").rstrip("/"),
            explicit_model or "grok-4-fast",
        )
    if openai_key:
        return openai_key, openai_base, explicit_model or "gpt-5.6-luna"
    raise RuntimeError("start Ollama or set OPENAI_API_KEY / XAI_API_KEY / HARNESS_API_KEY")


def get_provider(name: str) -> Provider:
    if name == "deterministic":
        return DeterministicProvider()
    if name == "scripted":
        return ScriptedProvider([])
    if name in {"openai_compat", "openai", "ollama", "ollama-cloud"}:
        provider = OpenAICompatProvider()
        try:
            key, base, _model = live_endpoint()
        except RuntimeError:
            return provider
        if "ollama.com" in base:
            provider.name = "ollama-cloud"
        elif key == "ollama" or "11434" in base:
            provider.name = "ollama"
        elif "openai.com" in base:
            provider.name = "openai"
        elif "x.ai" in base:
            provider.name = "xai"
        return provider
    raise ValueError(f"unknown provider: {name}")


def _call(name: str, arguments: dict) -> Completion:
    return Completion(tool_calls=[ToolCall(name=name, arguments=arguments, id=name)])


def _tool_history(messages: list[dict]) -> list[dict]:
    history = []
    for message in messages:
        if message.get("role") == "tool":
            history.append(message)
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                history.append(
                    {
                        "role": "assistant_call",
                        "name": call.get("name"),
                        "arguments": call.get("arguments") or {},
                    }
                )
    return history


def _has_tool(results: list[dict], name: str) -> bool:
    return any(item.get("name") == name for item in results)


def _count_tool(results: list[dict], name: str) -> int:
    return sum(1 for item in results if item.get("name") == name and item.get("role") == "tool")


def _last_tool(results: list[dict], name: str) -> dict | None:
    matches = [item for item in results if item.get("name") == name and item.get("role") == "tool"]
    return matches[-1] if matches else None


def _read_path(results: list[dict], path: str) -> str | None:
    for item in results:
        if item.get("role") != "tool" or item.get("name") != "read_file":
            continue
        arguments = item.get("arguments") or {}
        if arguments.get("path") == path:
            return item.get("content") or ""
    return None


def _shell_passed(content: str) -> bool:
    first = content.splitlines()[0] if content else ""
    return first.strip() == "exit 0"


def _openai_messages(messages: list[dict]) -> list[dict]:
    secrets = []
    for name in ("HARNESS_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY"):
        value = os.environ.get(name)
        if value:
            secrets.append(value)
    clean: list[dict] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        for key in secrets:
            content = content.replace(key, "[redacted]")
        if role == "assistant" and message.get("tool_calls"):
            clean.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [
                        {
                            "id": call.get("id") or "call",
                            "type": "function",
                            "function": {
                                "name": call.get("name"),
                                "arguments": json.dumps(call.get("arguments") or {}),
                            },
                        }
                        for call in message.get("tool_calls") or []
                    ],
                }
            )
        elif role == "tool":
            clean.append(
                {
                    "role": "tool",
                    "tool_call_id": message.get("tool_call_id") or message.get("name") or "call",
                    "content": content,
                }
            )
        else:
            clean.append({"role": role, "content": content})
    return clean
