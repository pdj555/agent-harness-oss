# Architecture

The public harness is a single Python package with hard boundaries. It is not a
platform of many agents. One principal agent does the work. Everything else
exists to give that agent authority, isolation, and proof.

```text
browser  ->  auth  ->  app  ->  runtime  ->  provider
                              |           ->  tools (authority)
                              |           ->  isolation (worktree)
                              |           ->  verification (pytest)
                              |           ->  review
                              '-> store (sqlite)
```

## Modules

| Module | Responsibility |
| --- | --- |
| `harness/auth.py` | scrypt hashes, session tokens |
| `harness/store.py` | users, sessions, durable runs |
| `harness/app.py` | HTTP API and static workspace |
| `harness/config.py` | allowlisted roots, provider name, data dir |
| `harness/authority.py` | path and role checks |
| `harness/isolation.py` | Git worktree / copied git stage, publish |
| `harness/tools.py` | list, search, read, edit, shell, git, delegate |
| `harness/provider.py` | provider protocol; deterministic and OpenAI-compatible |
| `harness/runtime.py` | principal loop, stop, repair |
| `harness/verification.py` | parent-run checks |
| `harness/review.py` | independent reviewer record |
| `harness/demo.py` | sample-repo demo entry |

## Authority

Agents do not receive the host filesystem. They receive tools. Each call is
checked against:

1. the caller's role (principal, helper, reviewer)
2. the isolated stage root
3. the stop flag, for mutating tools

The web client never sends raw paths. It sends a `repo_id` from
`workspace.roots`. Unknown ids are rejected.

## Isolation

Mutating work happens in a stage directory under `.harness/stages/<run_id>/`.
A selected path is treated as Git only when `git rev-parse --show-toplevel`
equals that path. Nested folders inside some other clone are copied, not
attached to the parent worktree. If the path is a Git root, the stage is a
detached Git worktree. Otherwise the files are copied and initialized as Git
inside the stage so diff and status still work. The source tree is unchanged
until `Stage.publish()` copies the verified delta. The web UI exposes publish
as an explicit step after verification.

## Verification

When the model stops proposing tool calls, the runtime runs
`run_checks(stage.root)`. That function executes pytest in the stage with a
filtered environment. The boolean `passed` comes from the process exit code.
There is no parameter for a model claim.

Completion also requires an independent review record (`role: reviewer`) whose
summary is not the principal's final text.

## Provider boundary

`get_provider(name)` is the only factory. Tests inject `ScriptedProvider`. The
demo uses `DeterministicProvider`. A live vendor implements the same
`complete(messages, tools)` method. Credentials stay in environment variables.

## Persistence

SQLite lives in `.harness/harness.db`. Run payloads include plan, events,
files, diff, checks, review, verification, blockers, and result. History is
per user.
