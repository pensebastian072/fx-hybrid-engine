# fxhy-ops-broker

Use this role for paper/live rails, broker-aware workflows, dashboard provenance, and artifact-truthfulness work.

## Read First

1. [`../../../AGENTS.md`](../../../AGENTS.md)
2. [`../../../src/fx_hybrid_engine/AGENTS.md`](../../../src/fx_hybrid_engine/AGENTS.md)
3. [`../../../ui/AGENTS.md`](../../../ui/AGENTS.md) when dashboard provenance is involved
4. [`SKILL.md`](SKILL.md)

## What This Folder Owns

- `SKILL.md` — ops and broker execution rules
- `agents/openai.yaml` — CLI-facing role descriptor

## Current System Truth To Preserve

- Local paper artifacts are real.
- Broker-aware plumbing exists.
- Broker-native routing and exact FX-futures mapping are still unfinished.
- The UI must stay aligned with backend truth from `artifacts/latest_run/` and `artifacts/mock/`.

## Validation Bias

- Use the real repo commands for the affected flow, such as `fxhe-paper-session`, `fxhe-phase6-precheck`, `fxhe-live-precheck`, targeted tests, or `make smoke`.
