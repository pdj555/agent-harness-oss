# Security model

## Trust boundaries

| Surface | Trust |
| --- | --- |
| Browser | Untrusted. Cannot pick arbitrary files. Talks JSON to loopback HTTP. |
| Session cookie | Bearer of identity. Random, hashed at rest, httpOnly. |
| Model | Untrusted. Proposes tool calls and text. Cannot set verdicts. |
| Tools | Trusted code. Enforce role, path, and stop. |
| Stage | The only tree the model may edit. |
| Source repository | Read-only until a verified publish. |
| Environment | Holds API keys. Stripped from tool subprocesses and redacted from events. |

## Authentication

- Sign up stores `scrypt$<salt>$<digest>`.
- Login verifies with `hmac.compare_digest`.
- Logout deletes the hashed session and the cookie.
- `/api/me`, `/api/repos`, `/api/runs` require a valid session. Bodies on 401
  contain only `{"error": "authentication required"}`.

## Path restriction

`resolve_in_root` rejects:

- empty paths
- absolute paths outside the stage
- `..` escapes after `Path.resolve()`
- direct `.git` access through file tools

Git status and diff run with `cwd` set to the stage.

## Shell

`run_shell` uses `shlex.split` (no `shell=True`), forces `cwd` to the stage,
replaces `python3` with the current interpreter, and passes a filtered
environment without provider credentials. Timeout is 60 seconds. Git
subprocesses use a filtered environment and `core.hooksPath=/dev/null`.

This is not an OS sandbox. A live model that can run Python can still touch
the host as the same user. Treat live vendors as code execution. Bind to
loopback. Keep `workspace.roots` small.

## Verification is not a tool the model owns

The model may run tests via `run_shell`. That output is evidence in the
transcript. The completion verdict is a separate parent-run of pytest in
`harness.verification`. A string such as `VERIFICATION_PASSED` in model text
has no effect.

## What this is not

It is not a multi-tenant cloud, an OS sandbox profile, or a substitute for
reviewing the diff. It is a local operator tool with explicit, auditable
limits. See [SECURITY.md](../SECURITY.md).
