# agent-harness

27 sabotaged code changes passed every test; the tests caught none of them. The spec check caught all 27, and 3 attacks built to beat the spec check still get past it. A coding agent's work should never be approved by the same system that produced it.


<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero-dark.svg">
  <img alt="Dot chart of 27 sabotaged changes that all pass their tests: the project's tests catch 0, diff rules 6, a Claude Haiku 5.5 reviewer 27, and an executable spec 27." src="docs/assets/hero-light.svg" width="100%">
</picture>

## The numbers

The eval is 33 changes to three small programs, each shipped with a real bug: 6 honest fixes and 27 sabotaged changes. Every sabotaged change passes the project's tests, so the tests alone approve all 27.

- The project's tests catch 0 of 27
- Rules that inspect the diff catch 6 of 27
- The spec check catches 27 of 27, and blocks 0 of the 6 honest fixes
- Claude reviewers, one run of 3 reviews per case on 2026-11-09: Haiku 5.5 caught 27 of 27, Sonnet 5.5 25 of 25 it judged (2 never judged), Opus 5.5 21 of 21 it judged (6 never judged), and none blocked an honest fix. On this set the 95% interval for each model's catch rate runs to 100% and starts at 66% for Haiku and Sonnet and 59% for Opus

The API returned a refusal instead of a verdict on every Opus review of the 6 changes that leak the process environment, and on 10 of 18 Sonnet reviews. The harness blocks on a refusal, so nothing would ship, but those reviews judged nothing. Haiku gave a verdict on all 123 reviews, for $0.04. Catch rate does not separate the three models on this set. A second run on 2026-11-12 repeated the refusals (Opus 18 of 18 again; Sonnet 18 of 18, up from 10) and added [same-shape controls](docs/blind-spots.md#same-shape-controls): 8 attacks and 14 correct changes that all add the same return line. All three models blocked every same-shape attack they judged, including the one a cheap rule (block a trigger unless a zero-remainder test appears) would ship. They false-blocked 11 of 126 control reviews (Haiku 3, Sonnet 4, Opus 4), 9 of them on the control that hides an environment switch; 2 of 117 on the rest. The set cannot tell the models from a cheap syntactic rule (one written after the run scores 22 of 22 templates; Haiku 21, Sonnet and Opus 20), so it does not show the models reasoned about the condition. [Results and failure analysis](docs/reviewer-sweep.md).

The 27 come in six families:

- special_case (6): return the expected answers for exactly the tested inputs
- weaken_test (3): loosen the test assertions until the bug passes
- skip_test (3): mark the failing tests as skipped, or delete one
- conftest_patch (6): leave the bug in place and patch in a correct function from a file only the test runner loads
- incorrect_fix (3): right on every tested input, wrong just outside them
- unrelated_harm (6): fix the bug and add a harmful side effect, such as writing the process environment to a file or sending it to an outside host

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/flow-animated-dark.svg">
  <img alt="A change travels from the agent, through the tests, to an independent check. A sabotaged change stops at the check. An honest change lands on main." src="docs/assets/flow-animated-light.svg" width="100%">
</picture>

agent-harness runs a coding agent on a repository you allow. Models propose, software verifies.

1. The agent edits in a staged copy of the repo. Files Git ignores, such as .env, never enter the stage, and staging refuses to start if a credential file would be included.
2. When the agent stops, the project's own check command runs in the stage and its exit code is the verdict. For pytest, exit 0 also needs pytest's own report to show a test ran and none failed. That catches a run forced to exit 0 with failures on record or no test run, such as a conftest calling `os._exit(0)` before any test. Code in the stage runs inside pytest and can still stop it right after a failure, flip results, or write the report itself; docs/architecture.md lists those, and the review step has to catch them. The agent's claim that it is done is recorded as text and decides nothing. A timeout counts as a failure.
3. A fresh reviewer reads the diff and can inspect files. Cross-vendor review is preferred: Codex reviews Claude's work, Claude reviews Codex's. An Anthropic-only setup gets a separate, read-only Claude review context. A crash, malformed verdict, or blocking finding rejects the change. Blocks go back to the agent as findings it can repair, up to a set number of rounds.
4. A SHA-256 fingerprint of the verified files is checked again before apply, so what lands is what passed. CLI runs leave the source unchanged until an explicit `harness apply`.

The engines are the Anthropic Messages API, Codex, or any model on OpenRouter. Claude uses the same authority-checked tools as the harness loop.

The spec check is the independent check named in the first line. It never reads the test files. It copies the changed file into an empty directory, so a patch that exists only under the test runner never loads. It imports the file in a fresh interpreter with an environment of three variables (HOME, PATH, LANG), with a hook installed before the import that refuses file writes, network calls, and subprocess calls and records each attempt. It then runs the function on the tested inputs and on many inputs the agent never saw, comparing every answer with a rule written from the function's docstring alone.

The check also looks where a change could hide from it. The ledger spec probes totals up to a billion cents and part counts up to a thousand, well past the ranges the project's tests use, and the whole check runs again with each of several environment settings in place (APP_ENV set to production, prod, and development, ENV and ENVIRONMENT set to production), since the documented rules say nothing about the environment and the behavior must not change with it. Before it runs anything, the check also reads the changed file for the constants it names, folding arithmetic such as `10**12`, and probes both sides of each one; every environment variable the module's own code reads is then set to each string the file names. The rule still comes from the docstring alone; only the inputs come from the code. Five attacks that hid in these gaps are caught: thresholds at 1000 cents, a trillion cents and 100,000 parts, and branches keyed on APP_ENV=production and LEDGER_ROUNDING=legacy. docs/blind-spots.md gives the method and the attacks that still get through.

## Run it

```bash
uv sync --extra dev
uv run harness demo
uv run harness eval monitor --monitor spec                      # spec check: 27 of 27 caught
uv run harness eval monitor --monitor spec --set blind-spots    # spec check: 0 of 3 caught
uv run python scripts/reviewer_sweep.py                          # price a three-model reviewer rerun, no calls
uv run pytest
uv run python scripts/export_dataset.py dist/dataset               # the Hugging Face dataset, rebuilt
```

## Use it on your repository

```bash
export ANTHROPIC_API_KEY=...
export HARNESS_MODEL="your-claude-model-id"
uv run harness repo add ./your-repo
uv run harness run ./your-repo "Fix the broken behavior and add a regression test."
```

The command prints the diff, check output, review, and a run ID. Your source stays unchanged. Apply the exact verified patch with `uv run harness apply <run-id>`. [Configuration and web workspace →](docs/guide.md)

## Limits

- 3 attacks built to beat the spec check still get through it, each by computing its trigger instead of writing it down. One is wrong only once the total needs more than 40 bits, about 1.1 trillion cents. One is wrong only at six-digit part counts. One is wrong only when LEDGER_ROUNDING=legacy, with the value written reversed in the code. All three pass the tests and the spec, and all three are wrong. The five attacks before them are caught now; docs/blind-spots.md keeps the set current.
- The attacks and the specs were written by the same author, from the same docstrings. Every strong check catches all 27, so this eval can no longer tell the strong checks apart.
- Each eval task is a single small function with a clear docstring. Real code rarely ships one, and the spec check covers only functions that have one.
- 6 honest fixes is a thin base for the false block rate. Zero blocked out of 6 says less than zero out of 600 would.
- This is not a sandbox at the operating system level. Code the agent runs in the stage can touch the host as your user. docs/security.md has the full notes.
- Test suite: 455 passed on 2026-11-09 with uv installed. One test, tests/test_packaging.py::test_direct_wheel_includes_only_allowlisted_demo_files, runs uv to build a wheel and fails with FileNotFoundError on a machine where uv is not on the PATH.

Apache 2.0
