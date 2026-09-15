---
name: fxhy-ops-broker
description: Ops, broker, paper/live, and artifact-truthfulness work for the fx-hybrid-engine repo. Use when work centers on Tastytrade, Lean or QuantConnect integration, paper-session and precheck flows, promotion and live-readiness logic, or dashboard behavior driven by run-state artifacts.
---

# FXHY Ops Broker

## Overview

Read the repo root `AGENTS.md`, this folder's `README.md`, `src/fx_hybrid_engine/AGENTS.md`, and `ui/AGENTS.md` when dashboard provenance is involved. Use this skill for broker-aware and ops-facing changes where truthful paper/live representation matters.

## Execution rules

- Preserve append-only artifact behavior and the contracts in `docs/CONTRACTS.md`.
- Keep local paper output truthful. Do not imply broker-native routing or live execution when the backend is still local paper only.
- If a task touches Tastytrade credentials or broker secrets, do not persist them and explicitly call out rotation if they were exposed.
- When changing dashboard run-state semantics, update the backend artifact logic and the dashboard API/types together.
- Prefer validation with the real repo commands for the affected path, such as `fxhe-paper-session`, `fxhe-phase6-precheck`, `fxhe-live-precheck`, targeted unit tests, or `make smoke`.

## Current system truth to preserve

- Local paper artifacts such as `paper_position_plan.json` and `paper_safety_summary.json` are real.
- Broker-native order routing, exact FX-futures contract mapping, and broker-native market data are not complete.
- The dashboard must stay aligned with backend truth from `artifacts/latest_run/` and `artifacts/mock/`.

## Required output

- Summarize what is actually real after the change.
- Name the exact validation commands that were run or still need to run.
- Call out any remaining blocker that would prevent broker-native or live claims.
