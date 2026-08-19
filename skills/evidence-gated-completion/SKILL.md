---
name: evidence-gated-completion
description: Use when changing verification, review, runtime completion, or any path that could mark a run done. Completion requires software evidence.
---

Models propose. Software verifies.

- `harness.verification.run_checks` owns `passed`. It reads a process exit code.
- Do not add a parameter, tool, or JSON field that lets model text set `passed`.
- Independent review is a distinct `role: reviewer` record. Do not copy the
  principal's final text into it.
- A failed check is status `failed`, never `completed`.
- Tests must drive the shipped runtime, not a reimplemented oracle.
