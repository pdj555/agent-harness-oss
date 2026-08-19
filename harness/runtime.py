from __future__ import annotations

import os

from harness.authority import PathDenied, PermissionDenied
from harness.config import Config
from harness.isolation import IsolationError, create_stage
from harness.provider import Completion, Provider
from harness.review import run_review
from harness.store import Store
from harness.tools import ToolError, execute, software_helper, tool_specs
from harness.verification import run_checks

SYSTEM = """You are the principal coding agent in a local harness.
Inspect the repository with tools, make a minimal isolated change, and stop.
Software will run tests and an independent review. Your text cannot mark work complete.
Do not request credentials. Do not touch files outside the worktree.
"""

DEFAULT_PLAN = [
    "Inspect the repository",
    "Identify the defect",
    "Apply an isolated fix",
    "Run the project's tests",
    "Independent review",
    "Record evidence",
]


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
            "tests and the sample demo. It is not a live model. Set provider.name to "
            "openai_compat and HARNESS_API_KEY to use a vendor model."
        )
    model = os.environ.get("HARNESS_MODEL")
    if model:
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
        stage = create_stage(repo.path, config.data_dir / "stages", run_id)
    except IsolationError as exc:
        store.update_run(run_id, status="failed", result=str(exc), blockers=["isolation"])
        return

    store.update_run(
        run_id,
        status="running",
        stage_path=str(stage.root),
        plan=list(DEFAULT_PLAN),
        investigating="Inspecting the repository boundary and tests.",
        active_work="Starting the principal agent.",
    )

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": run.objective},
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
            completion = provider.complete(messages, tools)
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
                store.update_run(run_id, active_work=f"{call.name}")
                try:
                    output = execute(
                        call.name,
                        call.arguments or {},
                        stage=stage,
                        role="principal",
                        helper=helper,
                        stopped=bool(current and current.stop_requested),
                    )
                    store.add_event(run_id, "action", f"{call.name} { _brief(call.arguments)}")
                    if call.name in {"edit_file", "run_shell", "git_diff", "git_status"}:
                        store.update_run(
                            run_id,
                            files_changed=stage.changed_files(),
                            diff=stage.diff(),
                        )
                    if call.name in {"git_diff", "git_status"}:
                        store.add_event(run_id, "artifact", output[:2000])
                    messages.append(
                        {
                            "role": "tool",
                            "name": call.name,
                            "tool_call_id": call.id,
                            "arguments": call.arguments or {},
                            "content": _redact(output)[:8000],
                        }
                    )
                except (PathDenied, PermissionDenied, ToolError) as exc:
                    detail = f"{call.name} denied: {exc}"
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
            continue

        store.update_run(run_id, active_work="Running verification.")
        evidence = run_checks(stage.root)
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
        store.update_run(run_id, review=review)
        store.add_event(run_id, "decision", review["summary"])

        if evidence.passed and review.get("passed"):
            if config.auto_publish:
                stage.publish()
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


def _assistant_message(completion: Completion) -> dict:
    return {
        "role": "assistant",
        "content": completion.text,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in completion.tool_calls
        ],
    }


def _brief(arguments: dict | None) -> str:
    if not arguments:
        return ""
    path = arguments.get("path") or arguments.get("command") or arguments.get("query") or ""
    return str(path)[:120]


def _redact(text: str) -> str:
    key = os.environ.get("HARNESS_API_KEY")
    if key:
        text = text.replace(key, "[redacted]")
    return text
