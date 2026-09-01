from __future__ import annotations

import json
import os
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE = PACKAGE_ROOT / "examples" / "sample-repo"

SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")
MIN_SECRET_LENGTH = 12


def _load_dotenv() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    for candidate in (Path.cwd() / ".env", PACKAGE_ROOT / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value
        break


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 7465
    workspace_roots: list[Path] = field(default_factory=list)
    provider_name: str = "deterministic"
    data_dir: Path = Path(".harness")
    auto_publish: bool = False
    max_steps: int = 24
    max_repairs: int = 2
    check_command: list[str] = field(default_factory=list)
    check_timeout: int = 300
    shell_timeout: int = 120
    keep_stages: int = 20
    provider_instance: Any = None


def secret_values() -> list[str]:
    """Environment values that must never reach a prompt, an event, or an artifact.

    Any variable whose name reads like a credential counts, not just the few
    this harness sets itself. Longest first, so an embedded secret is replaced
    before a value that merely contains it.
    """
    found = set()
    for name, value in os.environ.items():
        upper = name.upper()
        if not any(hint in upper for hint in SECRET_ENV_HINTS):
            continue
        cleaned = (value or "").strip()
        if len(cleaned) >= MIN_SECRET_LENGTH:
            found.add(cleaned)
    return sorted(found, key=len, reverse=True)


def redact(text: str) -> str:
    for value in secret_values():
        text = text.replace(value, "[redacted]")
    return text


def has_live_key() -> bool:
    return bool(
        os.environ.get("XAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("HARNESS_API_KEY")
        or os.environ.get("OLLAMA_API_KEY")
    )


def extra_repos_path(data_dir: Path) -> Path:
    return data_dir / "repos.json"


def load_extra_roots(data_dir: Path) -> list[Path]:
    path = extra_repos_path(data_dir)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    roots: list[Path] = []
    if not isinstance(raw, list):
        return []
    for item in raw:
        candidate = Path(str(item)).expanduser()
        if candidate.is_dir():
            roots.append(candidate.resolve())
    return roots


def add_extra_root(data_dir: Path, root: Path) -> Path:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    data_dir.mkdir(parents=True, exist_ok=True)
    roots = load_extra_roots(data_dir)
    resolved = [path.resolve() for path in roots]
    if root not in resolved:
        roots.append(root)
        extra_repos_path(data_dir).write_text(
            json.dumps([str(path) for path in roots], indent=2) + "\n",
            encoding="utf-8",
        )
    return root


def load_config(path: Path | None = None, *, prefer_live: bool = True) -> Config:
    _load_dotenv()
    config = Config(workspace_roots=[DEFAULT_SAMPLE] if DEFAULT_SAMPLE.is_dir() else [])
    candidate = path or Path("harness.toml")
    if candidate.is_file():
        raw = tomllib.loads(candidate.read_text(encoding="utf-8"))
        server = raw.get("server", {})
        workspace = raw.get("workspace", {})
        provider = raw.get("provider", {})
        data = raw.get("data", {})
        config.host = str(server.get("host", config.host))
        config.port = int(server.get("port", config.port))
        roots = workspace.get("roots", [])
        if roots:
            config.workspace_roots = [_resolve_root(item, candidate.parent) for item in roots]
        config.provider_name = str(provider.get("name", config.provider_name))
        config.data_dir = _resolve_root(data.get("dir", config.data_dir), candidate.parent)
        config.auto_publish = bool(workspace.get("auto_publish", config.auto_publish))
        config.check_command = _command(raw.get("verification", {}).get("command"))
        config.check_timeout = int(
            raw.get("verification", {}).get("timeout", config.check_timeout)
        )
        config.shell_timeout = int(
            raw.get("verification", {}).get("shell_timeout", config.shell_timeout)
        )
        config.keep_stages = int(data.get("keep_stages", config.keep_stages))
    if not config.workspace_roots and DEFAULT_SAMPLE.is_dir():
        config.workspace_roots = [DEFAULT_SAMPLE]
    env_provider = os.environ.get("HARNESS_PROVIDER")
    if env_provider:
        config.provider_name = env_provider
    elif prefer_live and config.provider_name == "deterministic":
        from harness.provider import ollama_available

        if has_live_key() or ollama_available():
            config.provider_name = "openai_compat"
    config.data_dir = config.data_dir.expanduser()
    if not config.data_dir.is_absolute():
        config.data_dir = Path.cwd() / config.data_dir
    extras = load_extra_roots(config.data_dir)
    seen = {path.resolve() for path in config.workspace_roots}
    for root in extras:
        if root.resolve() not in seen:
            config.workspace_roots.append(root)
            seen.add(root.resolve())
    return config


def _command(value: object) -> list[str]:
    """Read an operator-declared check command. Empty means the pytest default."""
    if not value:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list):
        return [str(part) for part in value if str(part)]
    raise ValueError("verification.command must be a string or a list of strings")


def _resolve_root(value: Path | str, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    return path
