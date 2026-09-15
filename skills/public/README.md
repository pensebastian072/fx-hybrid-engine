# Public Role Skills

This folder contains the four repo-tracked roles used to keep work scoped and repeatable.

## Shared Folder Layout

Each role folder should contain:

- `README.md` — quick human-facing guide for recall and handoff
- `SKILL.md` — role contract and execution rules
- `agents/openai.yaml` — CLI-facing descriptor used by the local skill system

## Roles

- [`fxhy-architect/`](fxhy-architect/) — planning, routing, and validation briefs for ambiguous or cross-cutting work
- [`fxhy-quant-engineer/`](fxhy-quant-engineer/) — current backend/algo/config work in `src/fx_hybrid_engine/`
- [`fxhy-ops-broker/`](fxhy-ops-broker/) — paper/live rails, broker-aware flows, and dashboard truthfulness
- [`fxhy-review-validator/`](fxhy-review-validator/) — findings-first review, regression checks, and final validation

## Read First

1. [`../../AGENTS.md`](../../AGENTS.md)
2. [`../../docs/DEVELOPER.md`](../../docs/DEVELOPER.md)
3. The role folder you need for the current task

## Validation

- Prefer `make ai-check` when available.
- Direct script equivalent: `python scripts\validate_repo_skills.py`
