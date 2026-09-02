# Architecture

The public harness is a single Python package with hard boundaries. It is not a
platform of many agents. One principal agent does the work. Everything else
exists to give that agent authority, isolation, and proof.

```text
browser  ->  auth  ->  app  ->  runtime  ->  provider
                              |          ->  tools (authority)
                              |          ->  isolation (worktree)
                              |          ->  verification (pytest)
                              |          ->  review
                              '- - - - - ->  store (sqlite)
```

## Modules

| Module | Responsibility |
| --- | --- |
| `harness/auth.py` | scrypt hashes, session tokens |
| `harness/store.py` | users, sessions, durable runs |
| `harness/app.py` | HTTP API and static workspace |
| `harness/config.py` | allowlisted roots, provider name, data dir |
| `harness/authority.py` | path and role checks |
| `harness/environment.py` | the interpreter and environment a stage runs |
| `harness/fs.py` | one pruning file walk and text guard |
| `harness/isolation.py` | Git worktree / copied git stage, publish |
| `harness/tools.py` | list, search, read, edit, write, shell, git, delegate |
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
attached to the parent worktree. `ensure_git_repo` uses the same root check,
so a stage under `.harness/` still gets its own repository and a real diff
even when that directory sits inside another clone. If the path is a Git root, the stage is a
detached Git worktree. Otherwise the files are copied and initialized as Git
inside the stage so diff and status still work. The source tree is unchanged
until `Stage.publish()` copies the verified delta. The web UI exposes publish
as an explicit step after verification.

For a Git root, the working-tree overlay comes from `git ls-files`: tracked
files plus nonignored untracked files. Ignored credentials, dependency trees,
and generated data are not copied into the stage. The copy fallback also
excludes credential-like env files, dependency directories, and harness state.
If a Git repository tracks or leaves an env credential file unignored, staging
fails with one action: add that file to `.gitignore`. Example, sample, and
template env files remain available.

`Stage.diff()` registers new paths with `--intent-to-add` before diffing, so a
file the agent created shows up for the reviewer, the UI, and the agent's own
`git_diff`, not just in the changed-file list.

Status, diff, and the changed-file list all exclude the scaffolding a run
leaves in the stage - `.home`, caches, dependency trees - so nothing the
harness created is ever reviewed or published. A git read that fails raises
instead of reading as "nothing changed".

A stage is a full worktree or copy, so they are kept by count: creating one
removes all but the newest `data.keep_stages` (20 by default). Publishing reads
the stage, so a run whose stage has been pruned reports that instead of
publishing nothing.

## Verification

When the model stops proposing tool calls, the runtime runs
`run_checks(stage.root)`. That function executes pytest in the stage with a
filtered environment. The boolean `passed` comes from the process exit code.
There is no parameter for a model claim.

`run_checks` returns evidence for every outcome instead of raising: a red
suite, a suite that outruns `check_timeout` (300 seconds by default), a suite
that cannot start, and a repository that collects no tests all come back as
`passed: false` with output that says which happened. A run therefore always
reaches a verdict a person can read; it never stalls in `running`.

Checks run with **the project's own interpreter**. A repository's tests need
that repository's dependencies, and the harness interpreter has its own, so a
real project would otherwise fail on its first import. When the source tree
carries a virtualenv (`.venv`, `venv`, `.virtualenv`, `env`), its interpreter
runs the checks with its `bin` directory first on PATH and `VIRTUAL_ENV` set;
otherwise the harness interpreter runs them. Nothing about this is declared:
software reads the tree.

The virtualenv stays in the source tree and is never copied into the stage. The
interpreter runs with the stage as its working directory, so the code under
test is the isolated copy - including when the project is installed into that
virtualenv in editable mode, which `tests/test_environment.py` pins.

pytest is the default command. A project that proves itself another way names
its command in `harness.toml`:

```toml
[verification]
command = ["npm", "test", "--silent"]
timeout = 600
```

That file belongs to the operator. A model cannot set it, and neither can the
repository being worked on, so the verdict stays outside the agent's reach.

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
