---
name: isolated-execution
description: Use when changing tools, path checks, git worktrees, publish, shell, or stop behavior.
---

- Resolve every file path with `resolve_in_root`. Deny escapes and `.git` edits.
- Mutate only the stage. Publish is a separate, verified step.
- Shell runs with `cwd=stage`, no `shell=True`, filtered env, timeout.
- After stop is requested, reject mutating tools. Record the skip.
- Reviewers cannot edit. Helpers do not require the user to manage them.
- Never add a browser filesystem or terminal surface.
