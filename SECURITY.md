# Security

## What this software does that is dangerous

The harness runs model-proposed shell commands and file edits against a
repository. Treat that as code execution. The product is designed for a
**local, single-operator** machine, bound to loopback, with an explicit
repository allowlist.

## Built-in controls

- Passwords are stored with scrypt. They are never written to run events.
- Sessions are random tokens stored only as SHA-256 hashes, in httpOnly
  `SameSite=Lax` cookies.
- Protected API routes return `{"error": "authentication required"}` without
  account or run data.
- Tools resolve paths inside the isolated worktree. Absolute paths and parent
  escapes are denied.
- There is no filesystem browser and no terminal in the web client.
- Verification is a parent-run pytest invocation. Model text cannot mark a
  check passed and cannot skip permission checks.
- Provider credentials are read from the environment and redacted from events.
- Stop is cooperative at tool boundaries: once requested, mutating tools are
  rejected.

## Reporting a vulnerability

Open a private GitHub security advisory on this repository, or email the
maintainer listed on the GitHub profile. Do not file a public issue that
includes a working exploit or leaked secrets.

## Operator checklist

- Keep `workspace.roots` small and intentional.
- Do not bind the server to a public interface.
- Do not commit `.harness/`, `.env`, or API keys.
- Run `python scripts/scan_secrets.py` and `uvx pip-audit` before publishing
  changes.
- Assume a live vendor will try to read files you did not intend. The allowlist
  and worktree are the boundary, not the prompt.
