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


class OpenAICompatProvider:
    name = "openai_compat"

    @staticmethod
    def build_payload(messages: list[dict], tools: list[dict], model: str) -> dict:
        return {
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

    def complete(self, messages: list[dict], tools: list[dict]) -> Completion:
        api_key, base, model = live_endpoint()
        payload = self.build_payload(messages, tools, model)
        payload["tool_choice"] = "auto"
        request = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"provider request failed: {exc}") from exc
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


def live_endpoint() -> tuple[str, str, str]:
    """Return (api_key, base_url, model) for a live vendor."""
    if os.environ.get("XAI_API_KEY"):
        return (
            os.environ["XAI_API_KEY"],
            os.environ.get("HARNESS_API_BASE", "https://api.x.ai/v1").rstrip("/"),
            os.environ.get("HARNESS_MODEL", "grok-4-fast"),
        )
    key = os.environ.get("HARNESS_API_KEY")
    if key:
        return (
            key,
            os.environ.get("HARNESS_API_BASE", "https://api.openai.com/v1").rstrip("/"),
            os.environ.get("HARNESS_MODEL", "gpt-4.1-mini"),
        )
    raise RuntimeError("set XAI_API_KEY or HARNESS_API_KEY for a live model")


def get_provider(name: str) -> Provider:
    if name == "deterministic":
        return DeterministicProvider()
    if name == "scripted":
        return ScriptedProvider([])
    if name in {"openai_compat", "openai"}:
        return OpenAICompatProvider()
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
    key = os.environ.get("HARNESS_API_KEY")
    clean: list[dict] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if key:
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
