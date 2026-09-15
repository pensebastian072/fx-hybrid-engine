# Repository Docs

Use this folder as the index for contributor guidance, contracts, and operational truth.

## Read First

1. [`../AGENTS.md`](../AGENTS.md)
2. [`../README.md`](../README.md)
3. [`DEVELOPER.md`](DEVELOPER.md)

## Key Documents

- [`DEVELOPER.md`](DEVELOPER.md) — contributor workflow, role usage, validation, and PR flow
- [`CONTRACTS.md`](CONTRACTS.md) — artifact and schema expectations
- [`OPERATIONS.md`](OPERATIONS.md) — operational behavior and run-state truth
- [`TREND_FEATURE_CONTRACT.md`](TREND_FEATURE_CONTRACT.md) — trend-model feature contract
- [`ML4T_INTEGRATION.md`](ML4T_INTEGRATION.md) — ML4T-related integration notes
- [`local_data_path_design.md`](local_data_path_design.md) — local data path design notes

## Workflow Notes

- Root `AGENTS.md` remains the canonical contributor contract for the repo.
- Use the folder guides in `skills/`, `scripts/`, `src/`, `config/`, `tests/`, and `ui/` to navigate back to the right implementation surface quickly.
- Keep this folder aligned with scoped `AGENTS.md` files and role-specific skill docs whenever the workflow changes.

## Validation

- Prefer `make ai-sync` and `make ai-check` when `make` is available.
- Direct script equivalents:
  - `python scripts\sync_agent_docs.py --write`
  - `python scripts\validate_repo_skills.py`
  - `python -m pytest tests\unit\test_agent_system.py -q`
