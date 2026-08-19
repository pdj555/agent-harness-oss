# Demo

The sample repository at `examples/sample-repo` is a tiny priority classifier
with inverted high/low labels. `test_tracker.py` encodes the documented spec
and fails until the labels are corrected.

## Command-line demo

```bash
uv sync --extra dev
uv run harness demo
```

This command:

1. copies the sample into `.harness/demo-repo` so the fixture in git stays put
2. runs the principal agent through the **deterministic** provider
3. executes pytest inside an isolated stage
4. records an independent review
5. publishes the verified fix into that demo copy
6. prints the status, check output, review, files, and diff

Run it twice. Each invocation resets the demo copy from the fixture, so both
runs should complete with a real code change and passing checks.

Expected observables:

- `status: completed`
- `verification_passed: True`
- pytest output from the sample tests
- a reviewer summary that is not the principal's "done" text
- a diff that changes `classify_priority`

A live vendor is optional. The gating demo is the deterministic path.

## Web demo

```bash
uv run harness serve
```

Open `http://127.0.0.1:7465`, create an account, select `sample-repo`, and
submit one objective. Watch plan, events, changed files, checks, and proof.
Press **Stop** to end an in-flight run.

Without `auto_publish`, the verified edit stays in the worktree. The UI still
shows the diff and evidence. Use **Apply to repository** to copy the checked
files into the selected repository. The canonical sample under `examples/`
remains the failing fixture until you apply.

Verification is `python -m pytest -q` run in the stage with a filtered
environment. The deterministic provider knows how to repair this sample; a
live vendor uses the same tools.

## Failure path

Point a `ScriptedProvider` at the sample and have it say "done" without
editing. The runtime runs pytest, records `passed: false`, and stores status
`failed`. That path is covered in `tests/test_runtime.py`.
