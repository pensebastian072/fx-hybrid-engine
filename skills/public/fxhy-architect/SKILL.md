---
name: fxhy-architect
description: Task scoping, source-of-truth routing, owner selection, and handoff planning for the fx-hybrid-engine repo. Use when a request is ambiguous, cross-cutting, spans backend and ops, needs a concrete implementation brief, or needs a clean handoff for another agent.
---

# FXHY Architect

## Overview

Read the repo root `AGENTS.md` first, then use this folder's `README.md` for the human-facing map. Use this skill to turn a vague or cross-domain request into an implementation-ready brief with one primary owner, explicit risks, and explicit validation commands.

## Workflow

1. Inspect the root `AGENTS.md` and the nearest scoped `AGENTS.md` for the touched path.
2. Identify the dominant domain: backend/algo, ops/broker, UI truthfulness, or docs/tooling.
3. Select exactly one primary executor:
   - `fxhy-quant-engineer` for backend algo/config work.
   - `fxhy-ops-broker` for paper/live/broker, artifact truthfulness, or dashboard provenance work.
4. Build a short brief with:
   - Goal
   - Current state
   - Primary owner
   - Likely files
   - Validation commands
   - Open risks or blockers
5. When the work will be handed off or resumed in another chat, capture the brief fields listed in this folder's `README.md`: goal, current state, primary owner, likely files, validation commands, and open risks.

## Required routing rules

- Start here when a request is unclear, multi-file, or crosses phase boundaries.
- If the request touches local paper or Tastytrade work, explicitly note that broker-native routing and exact FX-futures mapping are not complete.
- Do not route new feature work into `src/fx_lean_engine/`.
- Finish every non-trivial task with `fxhy-review-validator`.

## Output contract

- Always name the primary executor.
- Always include the smallest validation command set that can prove the change.
- Always call out blockers that would make a later agent overstate current system reality.
