---
name: fxhy-quant-engineer
description: Backend quant-engineering for the fx-hybrid-engine repo. Use when work centers on `src/fx_hybrid_engine` data, features, engines, regime logic, risk, portfolio, evaluation, config, or CLI behavior that changes backend trading logic or artifacts.
---

# FXHY Quant Engineer

## Overview

Read the repo root `AGENTS.md`, this folder's `README.md`, and `src/fx_hybrid_engine/AGENTS.md` first. Use this skill for current backend implementation work in the hybrid engine, not for legacy code or generic dashboard cleanup.

## Execution rules

- Work inside `src/fx_hybrid_engine/`, `config/default.yaml`, tests, and closely related docs.
- Do not route new feature work into `src/fx_lean_engine/` unless the task explicitly targets the legacy surface.
- Keep thresholds and tunables in config instead of hard-coding them.
- Preserve schema contracts, UTC timestamps, `run_id` usage, and `run_manifest.json` / `config_snapshot.yaml` behavior.
- Preserve the regime constants `TREND`, `CHOP`, and `RISK_OFF`.
- If a change affects artifacts or the main loop, update or add integration smoke coverage in addition to unit tests.

## When to hand off

- Hand off to `fxhy-ops-broker` if the change is mainly about broker integration, paper/live workflow behavior, or dashboard provenance driven by artifacts.
- Hand off to `fxhy-review-validator` after code and tests are ready.

## Required output

- Summarize changed backend surfaces.
- Name the targeted tests and any broader validation that was needed.
- Call out any artifact, config, or schema implications.
