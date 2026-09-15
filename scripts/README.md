# Repository Scripts

This folder contains the workflow-supporting scripts and helper utilities used around the core codebase.

## Read First

1. [`../AGENTS.md`](../AGENTS.md)
2. [`../docs/DEVELOPER.md`](../docs/DEVELOPER.md)
3. This README

## Agent And Workflow Scripts

- `sync_agent_docs.py` — regenerates `.github/copilot-instructions.md` from root `AGENTS.md`
- `validate_repo_skills.py` — validates the repo skill tree under `skills/public/`
- `install_repo_skills.py` — installs repo-tracked skills into the local skill registry
- `export_for_copilot.ps1` — repo-specific fallback for exporting pending patches

## Validation And Data Helpers

- `validate_backtest_artifacts.py` — validates backtest output shape
- `normalize_artifacts.py` — normalizes artifact data for downstream use
- `analyze_trades.py` — trade analysis helper

## Vendor, Cloud, And Setup Helpers

- `vendor_check.py`
- `vendor_setup.ps1`
- `run_cloud_phase1_verification.sh`
- `run_cloud_phase2_demo.sh`
- `run_cloud_real_backtest.sh`
- `run_cloud_smoke_backtest.sh`
- `run_phase1_verification.sh`

## Workflow Notes

- These scripts support the contributor and validation flow; keep their error messages contextual and explicit.
- Prefer repo-native entry points such as `make ai-sync`, `make ai-check`, and `make ai-install` when available, but keep the direct script entry points usable for environments without `make`.
