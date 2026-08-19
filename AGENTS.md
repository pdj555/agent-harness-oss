# Agent operating principles

This file is the contract for any coding agent working **in this public
repository**.

## Purpose

Build software that makes one user dramatically more capable. A user gives the
harness a software objective and should watch it inspect, plan, edit in
isolation, test, review, repair, and return verified results.

## Public boundary

This tree will be read by strangers and competitors.

Never add proprietary orchestration, private prompts or skills, company names
or internal terminology, capital/trading/energy/customer workflows, secrets,
private endpoints, credential maps, personal filesystem paths, historical run
data, or comments that reveal some other system's architecture.

If publishing a change would reveal an advantage that should stay private,
implement a simpler public equivalent instead.

## Verification rules

- Models propose. Software verifies.
- An agent saying "done" is not completion.
- Model output cannot mark verification passed.
- Model output cannot bypass permission checks.
- Do not claim a fix without running the relevant tests.
- Do not merge or publish unverified work.

## How to work here

1. Understand the objective.
2. Inspect the repository.
3. Identify uncertainty and research only what matters.
4. Make a concrete plan.
5. Delegate independent work only when it increases capability.
6. Execute changes in an isolated git worktree.
7. Test continuously.
8. Review assumptions. Use independent review for important work.
9. Repair failures without waiting for the user.
10. Return only decisions that genuinely need the user.

Act decisively. Do not ask the user to manage agents. Ask only when a decision
cannot safely be made from evidence.

## Quality standard

Prefer a small, understandable architecture over a clever one. Keep
implementation tasks narrowly owned. Write tests that would fail if the shipped
behavior were broken. Keep credentials out of prompts, fixtures, and run
artifacts.

## Skills

Project skills live in [`skills/`](skills/). Use them when the work matches.
