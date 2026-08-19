---
name: public-boundary
description: Enforce the public IP boundary when editing this repository. Use before adding docs, comments, configs, fixtures, prompts, or copied ideas.
---

Assume every byte will be read by competitors.

Never add proprietary orchestration, private prompts or skills, company names
or internal terminology, capital/trading/energy/customer workflows, secrets,
private endpoints, credential maps, personal filesystem paths, historical run
data, or comments that explain some other private architecture.

If a change would reveal a private advantage, write a simpler public equivalent.
When scanning a diff, treat any of those categories as a merge blocker.
