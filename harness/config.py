from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE = PACKAGE_ROOT / "examples" / "sample-repo"


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
    provider_instance: Any = None


def load_config(path: Path | None = None) -> Config:
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
    if not config.workspace_roots and DEFAULT_SAMPLE.is_dir():
        config.workspace_roots = [DEFAULT_SAMPLE]
    env_provider = os.environ.get("HARNESS_PROVIDER")
    if env_provider:
        config.provider_name = env_provider
    config.data_dir = config.data_dir.expanduser()
    if not config.data_dir.is_absolute():
        config.data_dir = Path.cwd() / config.data_dir
    return config


def _resolve_root(value: Path | str, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    return path
