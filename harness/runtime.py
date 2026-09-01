from __future__ import annotations

import os

from harness.authority import MUTATING_TOOLS, PathDenied, PermissionDenied
from harness.config import Config, redact
from harness.isolation import IsolationError, create_stage
from harness.leverage import scan as leverage_scan
from harness.provider import Completion, Provider
from harness.review import run_review
from harness.store import Store
from harness.tools import ToolError, execute, software_helper, tool_specs
from harness.verification import run_checks

SYSTEM = """You are a principal software agent hired to make the user more money.

Do the smallest change that ships, unblocks revenue, stops a loss, or removes a production risk.
Do not do demo theater, drive-by refactors, or work the user did not ask for.
If several defects exist, pick the one with the highest dollar or shipping leverage and prove it.
Inspect the repository with tools until you can name that change, then make it in the isolated worktree.
Never claim tests passed. Software verifies. If you cannot prove the result, do not stop as if you were done.
Ask the user only when a decision would spend money or cannot be resolved from evidence.
Do not request credentials. Do not touch files outside the worktree.
"""

DEFAULT_PLAN = [
    "Find the highest-leverage outcome",
    "Inspect the repository",
    "Change only what pays",
    "Prove it with the project's tests",
    "Independent review",
]

TOOL_OUTPUT_LIMIT = 8000
EVENT_LIMIT = 2000
TRANSCRIPT_BUDGET = 48_000
KEEP_RECENT_TOOLS = 8
ELISION_FLOOR = 400

NEXT_DOLLAR = (
    "Find the highest-leverage change that increases revenue or stops a loss, "
    "ship it in isolation, and prove it with the project's tests."
)


def configuration_answer(objective: str, provider: Provider) -> str | None:
    text = " ".join((objective or "").lower().split())
    if not any(
        phrase in text
        for phrase in ("what model", "which model", "what provider", "which provider", "what llm")
    ):
        return None
    if provider.name == "deterministic":
        return (
            "This run uses the deterministic provider: a local scripted agent for "
            "tests and the sample demo. It is not a live model. Start Ollama or set "
            "OPENAI_API_KEY for a real model."
        )
    from harness.provider import live_endpoint, reasoning_effort_for

    try:
        _key, _base, model = live_endpoint()
    except RuntimeError:
        model = os.environ.get("HARNESS_MODEL")
    if model:
        effort = reasoning_effort_for(model)
        if effort:
            return (
                f"This run uses the {provider.name} provider with model {model} "
                f"({effort} reasoning)."
            )
        return f"This run uses the {provider.name} provider with model {model}."
    return f"This run uses the {provider.name} provider."


def execute_run(run_id: str, *, store: Store, config: Config, provider: Provider) -> None:
    run = store.get_run(run_id)
    if run is None:
        return
    answer = configuration_answer(run.objective, provider)
    if answer:
        store.update_run(
            run_id,
            status="completed",
            plan=["Answer from runtime configuration"],
            investigating="",
            active_work="",
            result=answer,
            files_changed=[],
            diff="",
            verification={
                "passed": True,
                "command": "not applicable",
                "exit_code": 0,
                "output": "No repository checks; no code change was requested.",
            },
            review={
                "role": "reviewer",
                "passed": True,
                "summary": "No repository change requested.",
                "findings": [],
                "files_reviewed": [],
            },
        )
        store.add_event(run_id, "result", answer)
        return
    repo = store.repo_by_id(run.repo_id, config.workspace_roots)
    if repo is None:
        store.update_run(
            run_id,
            status="failed",
            result="Repository is not in the allowlist.",
            blockers=["repository not allowlisted"],
        )
        return
    try:
        stage = create_stage(
            repo.path,
            config.data_dir / "stages",
            run_id,
            keep_stages=config.keep_stages,
        )
    except IsolationError as exc:
        store.update_run(run_id, status="failed", result=str(exc), blockers=["isolation"])
        return

    scan_text = leverage_scan(stage.root)
    store.update_run(
        run_id,
        status="running",
        stage_path=str(stage.root),
        plan=list(DEFAULT_PLAN),
        investigating="Ranking leverage from tests, markers, and recent commits.",
        active_work="Software scan",
    )
    store.add_event(run_id, "evidence", scan_text[:EVENT_LIMIT])

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"{run.objective}\n\n"
                "SOFTWARE LEVERAGE SCAN (not model output):\n"
                f"{scan_text}\n"
                "Act on the highest-leverage item. Call set_plan with a live plan before editing."
            ),
        },
    ]
    tools = tool_specs("principal")
    repairs = 0

    def helper(objective: str) -> str:
        store.add_event(run_id, "action", f"delegate: {objective}")
        return software_helper(objective, stage)

    for _ in range(config.max_steps):
        current = store.get_run(run_id)
        if current is None:
            return
        if current.stop_requested:
            store.update_run(run_id, status="stopped", result="Stopped by the user.")
            return

        try:
            completion = provider.complete(within_budget(messages), tools)
        except Exception as exc:
            store.update_run(run_id, status="failed", result=f"Provider failed: {exc}", blockers=["provider"])
            return

        current = store.get_run(run_id)
        if current and current.stop_requested:
            store.update_run(run_id, status="stopped", result="Stopped by the user.")
            return

        if completion.tool_calls:
            messages.append(_assistant_message(completion))
            for call in completion.tool_calls:
                current = store.get_run(run_id)
                if current and current.stop_requested:
                    store.add_event(run_id, "decision", f"{call.name} skipped because stop was requested")
                    store.update_run(run_id, status="stopped", result="Stopped by the user.")
                    return
                store.update_run(run_id, active_work=_human_action(call.name, call.arguments))
                try:
                    if call.name == "set_plan":
                        _apply_plan(store, run_id, call.arguments or {})
                    output = execute(
                        call.name,
                        call.arguments or {},
                        stage=stage,
                        role="principal",
                        helper=helper,
                        stopped=bool(current and current.stop_requested),
                        shell_timeout=config.shell_timeout,
                    )
                    store.add_event(
                        run_id, "action", _human_action(call.name, call.arguments)
                    )
                    if call.name in MUTATING_TOOLS:
                        store.update_run(
                            run_id,
                            files_changed=stage.changed_files(),
                            diff=stage.diff(),
                        )
                    if call.name in {"git_diff", "git_status"}:
                        store.add_event(run_id, "artifact", output[:EVENT_LIMIT])
                    messages.append(
                        {
                            "role": "tool",
                            "name": call.name,
                            "tool_call_id": call.id,
                            "arguments": call.arguments or {},
                            "content": redact(output)[:TOOL_OUTPUT_LIMIT],
                        }
                    )
                except (PathDenied, PermissionDenied, ToolError) as exc:
                    _tool_failure(store, run_id, messages, call, f"{call.name} denied: {exc}")
                except Exception as exc:
                    # A bad argument from the model is evidence, not a dead run.
                    _tool_failure(store, run_id, messages, call, f"{call.name} failed: {exc}")
            continue

        store.update_run(run_id, active_work="Running verification.")
        try:
            evidence = run_checks(
                stage.root, command=config.check_command, timeout=config.check_timeout
            )
            files = stage.changed_files()
            diff = stage.diff()
            store.update_run(
                run_id,
                verification=evidence.as_dict(),
                files_changed=files,
                diff=diff,
                checks=[evidence.as_dict()],
            )
            store.add_event(
                run_id,
                "evidence",
                f"verification passed={evidence.passed} exit={evidence.exit_code}",
            )
            review = run_review(stage, evidence, provider)
        except Exception as exc:
            store.update_run(
                run_id,
                status="failed",
                result=f"Verification could not complete: {exc}",
                blockers=["verification error"],
                active_work="",
            )
            return
        store.update_run(run_id, review=review)
        store.add_event(run_id, "decision", review["summary"])

        if evidence.passed and review.get("passed"):
            if config.auto_publish:
                try:
                    stage.publish()
                except Exception as exc:
                    store.update_run(
                        run_id,
                        status="failed",
                        result=f"Publishing the verified change failed: {exc}",
                        blockers=["publish"],
                        active_work="",
                    )
                    return
                store.add_event(run_id, "result", "Published verified files into the selected repository.")
            result_text = (
                completion.text.strip()
                if completion.text
                else "Verified changes are in the isolated worktree."
            )
            store.update_run(
                run_id,
                status="completed",
                result=result_text,
                active_work="",
                investigating="Checks passed. Independent review recorded.",
            )
            return

        repairs += 1
        if repairs > config.max_repairs:
            store.update_run(
                run_id,
                status="failed",
                result="Checks did not pass.",
                blockers=["verification failed"],
                active_work="",
            )
            return
        store.update_run(run_id, active_work="Repairing after failed checks.")
        messages.append(
            {
                "role": "user",
                "content": (
                    "Software verification failed. The model cannot mark this passed. "
                    f"Output:\n{evidence.output[-4000:]}\nRepair the defect."
                ),
            }
        )

    store.update_run(
        run_id,
        status="failed",
        result="Reached the step limit without verification evidence.",
        blockers=["step limit"],
    )


def within_budget(messages: list[dict]) -> list[dict]:
    """Carry recent tool output in full and elide the rest.

    Every step resends the whole transcript, so an unbounded history costs the
    square of the run length in tokens and latency. Recent evidence decides the
    next call; older output stays reachable by running the tool again.
    """
    trimmed = list(messages)
    seen = 0
    carried = 0
    for index in range(len(trimmed) - 1, -1, -1):
        message = trimmed[index]
        if message.get("role") != "tool":
            continue
        content = message.get("content") or ""
        seen += 1
        if len(content) <= ELISION_FLOOR or (
            seen <= KEEP_RECENT_TOOLS and carried + len(content) <= TRANSCRIPT_BUDGET
        ):
            carried += len(content)
            continue
        trimmed[index] = {
            **message,
            "content": (
                f"(earlier {message.get('name') or 'tool'} output elided: {len(content)} "
                "characters; run the tool again if you still need it)"
            ),
        }
    return trimmed


def _tool_failure(store: Store, run_id: str, messages: list[dict], call, detail: str) -> None:
    store.add_event(run_id, "decision", detail)
    messages.append(
        {
            "role": "tool",
            "name": call.name,
            "tool_call_id": call.id,
            "arguments": call.arguments or {},
            "content": detail,
        }
    )


def _assistant_message(completion: Completion) -> dict:
    return {
        "role": "assistant",
        "content": completion.text,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in completion.tool_calls
        ],
    }


def _apply_plan(store: Store, run_id: str, arguments: dict) -> None:
    raw_steps = arguments.get("steps") or []
    steps = [str(step).strip() for step in raw_steps if str(step).strip()][:12]
    if not steps:
        return
    why = str(arguments.get("why") or "").strip()
    store.update_run(
        run_id,
        plan=steps,
        investigating=why or "Live plan recorded from evidence.",
        active_work=steps[0],
    )


def _human_action(name: str, arguments: dict | None) -> str:
    args = arguments or {}
    if name == "list_files":
        return f"Listed files ({args.get('pattern') or '*'})"
    if name == "read_file":
        return f"Read {args.get('path') or 'a file'}"
    if name == "search":
        return f"Searched for {args.get('query') or 'a pattern'}"
    if name == "edit_file":
        return f"Edited {args.get('path') or 'a file'}"
    if name == "write_file":
        return f"Wrote {args.get('path') or 'a file'}"
    if name == "run_shell":
        return f"Ran {str(args.get('command') or 'a command')[:80]}"
    if name == "git_status":
        return "Inspected git status"
    if name == "git_diff":
        return "Inspected git diff"
    if name == "set_plan":
        return "Updated the live plan"
    if name == "delegate":
        return f"Delegated: {str(args.get('objective') or '')[:80]}"
    return name
