from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.accounts import create_account
from harness.app import create_app
from harness.config import add_extra_root, load_config
from harness.demo import run_demo
from harness.store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Local coding-agent harness with isolated execution and evidence-gated results.",
    )
    parser.add_argument("--config", type=Path, default=None)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the local web app")
    demo = sub.add_parser("demo", help="run the sample-repository demo")
    demo.add_argument(
        "--objective",
        default="Find the highest impact reliability problem, fix it, and prove the result.",
    )
    users = sub.add_parser("user", help="operator account tools")
    user_sub = users.add_subparsers(dest="user_command")
    add_user = user_sub.add_parser("add", help="create a local account")
    add_user.add_argument("username")
    add_user.add_argument("--password", required=True)
    repos = sub.add_parser("repo", help="allowlisted repositories")
    repo_sub = repos.add_subparsers(dest="repo_command")
    add_repo = repo_sub.add_parser("add", help="allow a local git repository")
    add_repo.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    command = args.command or "serve"
    config = load_config(args.config, prefer_live=command != "demo")
    if command == "user":
        if args.user_command != "add":
            parser.error("user command required")
        config.data_dir.mkdir(parents=True, exist_ok=True)
        store = Store(config.data_dir / "harness.db")
        store.initialize()
        try:
            user = create_account(store, args.username, args.password)
        except ValueError as exc:
            print(exc)
            return 1
        print(f"created {user.username}")
        return 0
    if command == "repo":
        if args.repo_command != "add":
            parser.error("repo command required")
        try:
            root = add_extra_root(config.data_dir, args.path)
        except ValueError as exc:
            print(exc)
            return 1
        print(root)
        return 0
    if command == "demo":
        result = run_demo(config, objective=args.objective)
        print(f"status: {result.status}")
        if result.verification:
            print(f"verification_passed: {result.verification.get('passed')}")
            print(result.verification.get("output", "")[-2000:])
        if result.review:
            print(f"review: {result.review.get('summary')}")
        if result.files_changed:
            print("files:")
            for name in result.files_changed:
                print(f"  {name}")
        if result.diff:
            print(result.diff)
        if result.result:
            print(result.result)
        return 0 if result.status == "completed" else 1

    import uvicorn

    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
