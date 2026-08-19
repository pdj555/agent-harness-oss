# Agent Harness

A local coding-agent product. You sign in, pick an allowlisted repository, and
state one software objective. A principal agent inspects the repo, edits in an
isolated Git worktree, runs tests, and faces an independent review.

**Models propose. Software verifies.** An agent saying "done" is not completion.

This repository is intentionally small. It is meant to be studied: how an agent
receives authority, how repository changes stay isolated, how failures are
repaired, and how work is proven with evidence.

## Quick start

Python 3.12+ and Git are required.

```bash
uv sync --extra dev
uv run harness demo
uv run harness serve
```

The server binds to `127.0.0.1:7465`. Open that address, create a local
account, select `sample-repo`, and submit:

```text
Find the highest impact reliability problem in this repository, fix it, and prove the result.
```

The sample library ships with a real defect. Its tests fail until the agent
repairs `classify_priority`. The default **deterministic** provider walks the
same tool interface a live vendor would use, so the demo does not need a paid
API key.

## What you will see

The workspace shows actions, evidence, artifacts, decisions, and results:

- what is being investigated
- the current plan
- active work
- files changed and the isolated diff
- checks that actually ran
- independent review
- blockers
- the final software verdict

It does not stream private chain of thought. Stop ends the run; no further
mutating tool call is accepted.

## How it is put together

| Boundary | Job |
| --- | --- |
| Auth | Local accounts, scrypt password hashes, httpOnly sessions, protected routes |
| Workspace | Repository picker limited to configured roots. No filesystem browser |
| Runtime | One principal agent. Delegation is optional help, not a worker fleet |
| Provider | Replaceable. `deterministic` for tests and demo; `openai_compat` for a live vendor |
| Tools | List, search, read, edit, shell, git status/diff — all path-checked |
| Isolation | Git worktree (or a copied git repo). Source is unchanged until publish |
| Verification | Parent process runs pytest. Model output cannot set `passed` |
| Review | A distinct reviewer record, not the principal's "done" text |
| Persistence | SQLite run history under `.harness/` |

See [docs/architecture.md](docs/architecture.md),
[docs/agent-runtime.md](docs/agent-runtime.md),
[docs/security.md](docs/security.md), and [docs/demo.md](docs/demo.md).

## Configuration

Copy [harness.example.toml](harness.example.toml) to `harness.toml`.

```toml
[workspace]
roots = ["examples/sample-repo"]

[provider]
name = "deterministic"
```

A live OpenAI-compatible vendor uses environment variables only. Never put keys
in config, prompts, or run artifacts:

```bash
export HARNESS_PROVIDER=openai_compat
export HARNESS_API_KEY=...
export HARNESS_API_BASE=https://api.openai.com/v1
export HARNESS_MODEL=gpt-4.1-mini
```

Then set `provider.name = "openai_compat"` in `harness.toml`.

## Tests and checks

```bash
uv run pytest
uv run ruff check harness tests
uv run python scripts/scan_secrets.py
uvx pip-audit
uv build
```

## Public boundary

This is a standalone public product. Do not contribute proprietary orchestration,
private prompts, private skills, personal machine paths, secrets, or any
capital, trading, energy, customer, or company-specific workflow.

Operating rules for agents working in this repository live in
[AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
