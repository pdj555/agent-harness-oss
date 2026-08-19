# CLAUDE.md

Instructions for Claude Code and other delegated agents working in
`agent-harness-oss`.

## Product

This is a public local coding-agent harness. Users create an account, select an
allowlisted repository, and submit one objective. The principal agent inspects,
edits in an isolated Git worktree, runs tests, and is independently reviewed.
Software, not the model, decides completion.

## Quality standard

- Small enough to study, strong enough to remember.
- No placeholders pretending to be features.
- Tests cover auth, path restriction, isolation, verification, review, stop,
  and the sample-repo demo.
- Match existing code. Do not recreate a private multi-round orchestration
  machine.

## Public boundary

Do not copy or invent:

- proprietary orchestration, private prompts, or private skills
- company-specific integrations or internal terminology
- capital, trading, energy, customer, or business workflows
- secrets, private endpoints, credential topology
- personal home-directory paths
- comments that describe a private system

If unsure, leave it out.

## Verification rules

Models propose. Software verifies.

- `harness.verification.run_checks` is the only source of `passed`.
- Permission checks live in `harness.authority`. Tool execution cannot skip them.
- Stop must prevent further successful mutating work.
- Run `uv run pytest` and `uv run ruff check harness tests` before claiming done.

## Operating principles

Inspect, plan, isolate, test, review, repair. Ask the user only when evidence
cannot decide. Do not make the user manage agents.

See [AGENTS.md](AGENTS.md) and [docs/architecture.md](docs/architecture.md).
