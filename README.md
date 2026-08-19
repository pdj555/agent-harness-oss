# Agent Harness

A local coding agent you hire against an outcome, not a chat pane.

You allowlist a real Git repository, state the change that makes money, and
watch one principal agent inspect, edit in an isolated worktree, run the
project's tests, and take independent review. **Apply** is explicit. An agent
saying "done" is not completion. Software verifies.

Cursor is a copilot in your editor. This is an operator: isolated execution,
proof, then a decision to land the diff.

## Run it for real

```bash
export XAI_API_KEY=...          # https://console.x.ai
uv sync --extra dev
uv run harness user add preston --password 'choose-your-own'
uv run harness repo add /path/to/the/repo/that/prints/money
uv run harness serve
```

Open `http://127.0.0.1:7465`, log in, pick that repository, and submit an
objective such as:

```text
Ship the change that most increases revenue or stops a loss, and prove it.
```

If `XAI_API_KEY` is set, serve uses xAI (`grok-4-fast` by default). Override
with `HARNESS_MODEL`. `harness demo` stays on the scripted sample agent so
CI and first-run checks do not need a vendor.

## Why this is not a chat demo

- Models propose. Pytest and independent review decide.
- Mutating work happens in a Git worktree. The source tree does not move
  until you apply a verified delta.
- The browser cannot create accounts or open arbitrary files.
- Stop ends mutating work. History is durable.

## Sample demo (no API key)

```bash
uv run harness demo
```

That path repairs a known defect in `examples/sample-repo` so the loop can be
proven without a vendor. It is not the product.

## Configuration

Copy [harness.example.toml](harness.example.toml) to `harness.toml` if you need
to bind a different port or extra roots. Additional repositories:

```bash
uv run harness repo add ~/code/your-repo
```

## Tests

```bash
uv run pytest
uv run ruff check harness tests
uv run python scripts/scan_secrets.py
uvx pip-audit
uv build
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
