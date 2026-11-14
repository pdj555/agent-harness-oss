from __future__ import annotations

import argparse
import shlex
import sys
from dataclasses import replace
from pathlib import Path

from harness.accounts import create_account
from harness.app import create_app
from harness.config import Config, add_extra_root, load_config
from harness.demo import run_demo
from harness.isolation import IsolationError, Stage
from harness.runtime import execute_run
from harness.store import Run, Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Local coding-agent harness with isolated execution and evidence-gated results.",
    )
    parser.add_argument("--config", type=Path, default=None)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the local web app")
    run = sub.add_parser("run", help="prepare a verified change in an allowlisted repository")
    run.add_argument("repo", type=Path)
    run.add_argument("objective")
    apply = sub.add_parser("apply", help="apply a verified run to its repository")
    apply.add_argument("run_id")
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
    evals = sub.add_parser("eval", help="measure the harness")
    eval_sub = evals.add_subparsers(dest="eval_command")
    monitor = eval_sub.add_parser("monitor", help="how often the reviewer catches an agent gaming its tests")
    monitor.add_argument("--monitor", choices=["software", "spec", "claude", "codex"], default="software")
    monitor.add_argument(
        "--model", default=None, help="reviewer model; required for Claude, optional for Codex"
    )
    monitor.add_argument(
        "--specs",
        type=Path,
        default=None,
        help="with --monitor spec: a directory of <repo>.py specs to use instead of the built-in ones",
    )
    monitor.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        default=None,
        help="with --monitor claude: pin the reviewer's effort; unset, each model uses its default",
    )
    monitor.add_argument("--trials", type=int, default=1, help="runs per case; model monitors vary")
    monitor.add_argument(
        "--set",
        choices=["main", "blind-spots", "same-shape", "paired"],
        default="main",
        help="main: the 33 published cases; blind-spots: attacks the spec is known to miss; "
        "same-shape: attacks and correct controls that add one return line, differing only in its condition; "
        "paired: 24 generated attack and control pairs that only arithmetic tells apart",
    )
    monitor.add_argument("--case", action="append", default=None, help="run only this case id (repeatable)")
    monitor.add_argument("--out", type=Path, default=None, help="report directory")
    monitor.add_argument("--jobs", type=int, default=4, help="cases reviewed in parallel (default 4)")
    monitor.add_argument(
        "--max-errors",
        type=int,
        default=5,
        help="stop after this many reviewer errors in a row, 0 to never stop (default 5)",
    )
    monitor.add_argument(
        "--rescore", type=Path, default=None, help="rescore a saved results.json instead of running reviewers"
    )
    args = parser.parse_args(argv)
    command = args.command or "serve"
    if command == "eval":
        if args.eval_command != "monitor":
            parser.error("eval command required")
        return _monitor_eval(args)
    config = load_config(args.config, prefer_live=command != "demo")
    if command == "run":
        if not args.objective.strip():
            parser.error("objective must not be blank")
        return _run(args.repo, args.objective.strip(), config, config_path=args.config)
    if command == "apply":
        return _apply(args.run_id, config)
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


def _cli_store(config: Config) -> Store:
    store = Store(config.data_dir / "harness.db")
    store.initialize()
    return store


def _run(repo_path: Path, objective: str, config: Config, *, config_path: Path | None) -> int:
    store = _cli_store(config)
    root = repo_path.expanduser().resolve()
    repo = next((item for item in store.list_repos(config.workspace_roots) if item.path == root), None)
    command = "harness" + (f" --config {shlex.quote(str(config_path))}" if config_path else "")
    if repo is None:
        print(f"Repository is not allowlisted. Add it with: {command} repo add {shlex.quote(str(root))}")
        return 1
    # This identity is local to the CLI and cannot be created or logged into through account tools.
    user = store.get_user_by_username("local-cli") or store.create_user("local-cli", "disabled")
    run = store.create_run(user.id, repo.id, objective)
    print(f"run: {run.id}", flush=True)
    try:
        execute_run(
            run.id,
            store=store,
            config=replace(config, auto_publish=False),
            provider=config.provider_instance,
        )
    except KeyboardInterrupt:
        store.request_stop(run.id)
        store.add_event(run.id, "decision", "Stopped from the command line.")
        store.update_run(run.id, status="stopped", result="Stopped by the user.", active_work="")
        print("status: stopped")
        return 130
    finished = store.get_run(run.id)
    if finished is None:
        print("Run record is missing.")
        return 1
    _print_run(finished)
    if finished.status == "completed" and (finished.verification or {}).get("stage_digest"):
        print(f"Apply with: {command} apply {finished.id}")
    return 0 if finished.status == "completed" else 1


def _print_run(run: Run) -> None:
    print(f"status: {run.status}")
    if run.stage_path:
        print(f"stage: {run.stage_path}")
    if run.verification:
        verification = run.verification
        print(f"checks: {verification.get('command', '')} (exit {verification.get('exit_code')})")
        output = str(verification.get("output") or "").strip()
        if output:
            print(output[-4000:])
    if run.review:
        print(f"review: {run.review.get('summary', '')}")
        for finding in run.review.get("findings") or []:
            print(f"  {finding}")
    if run.diff:
        print(run.diff)
    if run.result:
        print(run.result)


def _apply(run_id: str, config: Config) -> int:
    store = _cli_store(config)
    run = store.get_run(run_id)
    if run is None:
        print("Run not found. Use the same configuration as the original run.")
        return 1
    if run.published_at:
        print(f"Run {run_id} was already applied.")
        return 0
    if (
        run.status != "completed"
        or run.stop_requested
        or not (run.verification or {}).get("passed")
        or not (run.review or {}).get("passed")
    ):
        print("Only a verified completed run can be applied.")
        return 1
    repo = store.repo_by_id(run.repo_id, config.workspace_roots)
    if repo is None:
        print("The repository is no longer allowlisted.")
        return 1
    digest = (run.verification or {}).get("stage_digest")
    if not digest or not run.stage_path or not Path(run.stage_path).is_dir():
        print("The verified stage is missing. Run the objective again.")
        return 1
    try:
        Stage(id=run.id, source=repo.path, root=Path(run.stage_path)).publish(expected_digest=digest)
    except IsolationError as exc:
        print(f"Cannot apply: {exc}")
        return 1
    store.add_event(run_id, "result", "Published verified files into the selected repository.")
    store.mark_published(run_id)
    print(f"Applied run {run_id} to {repo.name}.")
    return 0


def _monitor_eval(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from harness.evals.cases import BLIND_SPOTS, CASES, PAIRED_CASES, SAME_SHAPE_CASES
    from harness.evals.monitor import (
        EvalAborted,
        model_monitor,
        rescore,
        run_eval,
        software_monitor,
        spec_monitor,
        spec_monitor_from,
        write_report,
    )

    if args.rescore is not None:
        try:
            name, results = rescore(args.rescore)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"cannot rescore {args.rescore}: {exc}")
            return 1
        out = args.out or args.rescore.parent / "rescored"
        summary = write_report(results, out, monitor_name=name)
        _print_summary(summary, out)
        return _exit_code(summary)

    if args.specs is not None and args.monitor != "spec":
        print("--specs only works with --monitor spec")
        return 1
    pool = {"blind-spots": BLIND_SPOTS, "same-shape": SAME_SHAPE_CASES, "paired": PAIRED_CASES}.get(
        args.set, CASES
    )
    cases = pool
    if args.case:
        known = {case.id for case in pool}
        unknown = sorted(set(args.case) - known)
        if unknown:
            print(f"unknown case: {', '.join(unknown)}")
            return 1
        cases = [case for case in pool if case.id in set(args.case)]
    if args.monitor == "software":
        monitor, trials, name = software_monitor, 1, "software rules"
    elif args.monitor == "spec" and args.specs is not None:
        if not args.specs.is_dir():
            print(f"no such spec directory: {args.specs}")
            return 1
        monitor, trials, name = spec_monitor_from(args.specs), 1, f"executable spec from {args.specs.name}"
    elif args.monitor == "spec":
        monitor, trials, name = spec_monitor, 1, "executable spec, side effects blocked"
    else:
        try:
            monitor = model_monitor(args.monitor, args.model, effort=args.effort)
        except Exception as exc:
            print(exc)
            return 1
        detail = ", ".join(part for part in (args.model, args.effort and f"effort {args.effort}") if part)
        trials, name = args.trials, args.monitor + (f" ({detail})" if detail else "")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or Path(".harness") / "evals" / f"monitor-{args.monitor}-{stamp}"
    jobs = 1 if args.monitor == "software" else max(1, args.jobs)
    try:
        results = run_eval(
            monitor,
            trials=trials,
            cases=cases,
            progress=print,
            jobs=jobs,
            max_consecutive_errors=0 if args.monitor == "software" else args.max_errors,
        )
    except EvalAborted as exc:
        print(f"{exc}; fix the reviewer (key, model name, network) and run again")
        summary = write_report(exc.results, out, monitor_name=name)
        _print_summary(summary, out)
        return 1
    summary = write_report(results, out, monitor_name=name)
    _print_summary(summary, out)
    return _exit_code(summary)


def _exit_code(summary: dict) -> int:
    """Non-zero when any case is invalid or went unjudged, so a broken run never reads as success."""
    if summary["invalid_cases"] or summary["unjudged_cases"] or not summary["judged_trials"]:
        return 1
    return 0


def _print_summary(summary: dict, out: Path) -> None:
    catch = summary["monitor"]["catch_rate"]["rate"]
    false_block = summary["monitor"]["false_block_rate"]["rate"]
    print(f"catch rate: {catch:.0%}" if catch is not None else "catch rate: n/a")
    print(f"false-block rate: {false_block:.0%}" if false_block is not None else "false-block rate: n/a")
    errors = summary["monitor"]["reviewer_errors"]
    if errors:
        print(f"reviewer errors (excluded from rates): {errors}")
    print(f"report: {out / 'report.md'}")


if __name__ == "__main__":
    sys.exit(main())
