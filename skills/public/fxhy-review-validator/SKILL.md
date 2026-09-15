---
name: fxhy-review-validator
description: Review, validation, acceptance gating, and docs-contract sync for the fx-hybrid-engine repo. Use when a change needs findings-first review, targeted regression checks, artifact or schema validation, AGENTS or skill sync, or final release-readiness confirmation.
---

# FXHY Review Validator

## Overview

Read the repo root `AGENTS.md` and this folder's `README.md` first. Use this skill at the end of any non-trivial task and for direct review requests so delivery quality stays consistent across backend, ops, and documentation changes.

## Review rules

- Present findings first for review requests. Order them by severity and point to the exact file or behavior at risk.
- Check for missing tests, schema drift, stale docs, and overstatements about paper/live status.
- If AGENTS files, skills, or repo agent tooling changed, require `make ai-sync` and `make ai-check`.
- If backend behavior changed, require targeted tests and any broader smoke or contract validation the scope needs.
- If artifact contracts changed, require validator and docs updates in the same change.

## Acceptance checklist

- Root `AGENTS.md` remains the source of truth.
- `.github/copilot-instructions.md` matches generated output.
- Repo skills validate cleanly.
- README and scoped AGENTS files match the implemented behavior.
- Local paper is still described truthfully.

## Required output

- For review requests, list findings first.
- For implementation close-out, report validation status, residual risks, and any missing follow-up work.
