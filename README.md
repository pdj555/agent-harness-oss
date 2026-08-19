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
# Cheapest live path: local Ollama, already installed.
# ollama serve && ollama pull gpt-oss:20b
uv sync --extra dev
uv run harness user add preston --password 'choose-your-own'
uv run harness repo add /path/to/the/repo/that/prints/money
uv run harness serve
```

Open `http://127.0.0.1:7465`, log in, pick that repository, and click
**Next dollar**. Software scans tests, TODO markers, and recent commits; the
agent writes a live plan from that evidence, ships in isolation, and stops
when checks pass. You can still type a specific objective.

Serve prefers **local Ollama** when it is running (`gpt-oss:20b` if installed,
never a `:cloud` tag unless you set `HARNESS_MODEL`). That is $0. Ollama Cloud
is a flat $0 / $20 / $100 quota for models that will not fit on your machine.
Pay-per-token OSS hosts (Groq, Fireworks, DeepInfra) are cheaper than Cloud Pro
if you only need bursts of a 120B model.

`harness demo` stays on the scripted sample agent so CI does not need a vendor.

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
