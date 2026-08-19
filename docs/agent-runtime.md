# Agent runtime

The runtime is a loop, not a workflow engine.

```text
queued -> running -> {completed | failed | stopped}
```

## Loop

1. Load the run, resolve the allowlisted repository, create a stage.
2. Ask the provider for a completion with the principal tool specs.
3. If stop was requested, halt. Mutating tools are rejected.
4. If the completion contains tool calls, execute each one through
   `harness.tools.execute` and append redacted results.
5. If the completion is plain text, **ignore any claim of success** and run
   `run_checks`.
6. Run independent review against the diff and the check output.
7. If checks and review passed, optionally publish, then mark `completed`.
8. If checks failed, append the captured output and let the principal repair,
   up to `max_repairs`. Then mark `failed`.

Events recorded for the UI are actions, evidence, artifacts, decisions, and
results. They are not a chain of thought dump.

## Tools

| Tool | Principal | Helper | Reviewer |
| --- | --- | --- | --- |
| list_files, search, read_file, git_status, git_diff | yes | yes | yes |
| edit_file, run_shell | yes | yes | no |
| delegate | yes | no | no |

`delegate` runs a software helper that inspects the stage and returns evidence.
The user never manages that helper.

## Independent review

`harness.review.run_review` always writes `role: "reviewer"`. Its `passed`
flag is computed from the isolated diff, not from pytest's exit code:

- tests must still exist in the stage
- there must be an isolated change
- tests may not change unless an implementation file also changed

Completion requires **both** `verification.passed` and `review.passed`. Green
checks with no implementation change do not complete. The review summary is
never the principal's "done" text.

## Stop

`POST /api/runs/{id}/stop` sets `stop_requested`. The loop checks the flag
before and after provider calls, and before each tool. A mutating call after
stop raises and is recorded as skipped.

## Providers

- `deterministic` — used by tests and `harness demo`. It calls the same tools.
- `scripted` — test double with a programmed list of completions.
- `openai_compat` — HTTP `chat/completions` with tool calls. Requires
  `HARNESS_API_KEY`.

Swap providers without changing the runtime.
