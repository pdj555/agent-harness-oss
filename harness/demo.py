from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from harness.config import DEFAULT_SAMPLE, Config
from harness.isolation import ensure_git_repo
from harness.provider import get_provider
from harness.runtime import execute_run
from harness.store import Run, Store


def run_demo(config: Config, objective: str = "Fix the failing tests and prove it.") -> Run:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config = _prepare_demo_workspace(config)
    store = Store(config.data_dir / "harness.db")
    store.initialize()
    user = store.get_user_by_username("demo")
    if user is None:
        user = store.create_user("demo", "scrypt$not-used$not-used")
    repos = store.list_repos(config.workspace_roots)
    if not repos:
        raise RuntimeError("no allowlisted repositories")
    run = store.create_run(user.id, repos[0].id, objective)
    provider = config.provider_instance or get_provider(config.provider_name)
    execute_run(run.id, store=store, config=config, provider=provider)
    finished = store.get_run(run.id)
    if finished is None:
        raise RuntimeError("demo run disappeared")
    return finished


def _prepare_demo_workspace(config: Config) -> Config:
    roots = [path.resolve() for path in config.workspace_roots]
    if not roots:
        return config
    if DEFAULT_SAMPLE.is_dir() and roots[0] == DEFAULT_SAMPLE.resolve():
        dest = config.data_dir / "demo-repo"
        if dest.exists():
            shutil.rmtree(dest)
        _copy_tree(DEFAULT_SAMPLE, dest)
        ensure_git_repo(dest)
        return replace(config, workspace_roots=[dest], auto_publish=True)
    return config


def _copy_tree(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.name in {".git", ".harness", "__pycache__"}:
            continue
        target = dest / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
