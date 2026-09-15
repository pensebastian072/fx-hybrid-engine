# Configuration

This folder contains the canonical config entry points and related checked-in config assets.

## Read First

1. [`../AGENTS.md`](../AGENTS.md)
2. [`../README.md`](../README.md)
3. [`default.yaml`](default.yaml)
4. [`../src/fx_hybrid_engine/utils/config.py`](../src/fx_hybrid_engine/utils/config.py)

## Important Files

- `default.yaml` — primary trader-tunable config surface
- `ladder.yaml` — ladder-related settings
- `pairs_policy.yaml` — pair policy configuration
- `hmm_model.pkl` and `trend_model.pkl` — checked-in model artifacts referenced by config and workflows

## Workflow Notes

- Keep tunable thresholds in config instead of hard-coding them in code paths.
- When config behavior changes, update the nearest docs and validation guidance in the same change.
