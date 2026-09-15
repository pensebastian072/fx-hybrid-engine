# fxhy-architect

Use this role when a request is ambiguous, cross-cutting, or needs a clean implementation brief before code changes begin.

## Read First

1. [`../../../AGENTS.md`](../../../AGENTS.md)
2. [`../../../docs/DEVELOPER.md`](../../../docs/DEVELOPER.md)
3. [`SKILL.md`](SKILL.md)

## What This Folder Owns

- `SKILL.md` — routing rules, brief shape, and role contract
- `agents/openai.yaml` — CLI-facing role descriptor

## Expected Brief Shape

When this role hands work off or sets up a later session, include:

- Goal
- Current state
- Primary owner
- Likely files
- Validation commands
- Open risks or blockers

## Typical Handoff

- Start here for unclear or multi-domain work.
- Route implementation to exactly one primary executor.
- Finish non-trivial work with `fxhy-review-validator`.
