# Contributing

This repository is a public demonstration of a serious local coding-agent
product. Changes should make a user more capable, or make the architecture
easier to study. They should not make the system larger for its own sake.

## Public boundary

Assume competitors will read every byte.

Do **not** contribute:

- proprietary orchestration algorithms or private prompts
- private skills, internal research, or company-specific integrations
- capital, trading, energy, customer, or business workflows
- secrets, private endpoints, credential topology
- personal home-directory paths or private git history
- comments that explain some other private system's architecture

If you are unsure whether something is distinctive private intellectual
property, leave it out and write a simpler public equivalent.

## Quality

- Tests drive shipped functions from their real entry points.
- An agent saying "done" is not completion. Software verification is.
- Keep the principal agent capable. Do not add worker theater.
- Match the existing modules: auth, UI, runtime, provider, tools, isolation,
  verification, review, persistence.
- User-facing copy should say what happened and what to do next.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check harness tests
uv run python scripts/scan_secrets.py
```

Read [AGENTS.md](AGENTS.md) before making agent-driven changes.
