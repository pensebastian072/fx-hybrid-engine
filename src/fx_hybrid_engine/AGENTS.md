# AGENTS.md - current backend surface

This package is the authoritative backend implementation for the repository.

## Priorities

- Read the repo root `AGENTS.md` first.
- Contributor workflow details live in `docs/DEVELOPER.md`.
- Folder navigation for this package lives in `README.md` in this directory.
- Keep tunables in `config/default.yaml` and the dataclasses under `utils/config.py`.
- Preserve the contracts in `docs/CONTRACTS.md` and the ops behavior documented in `docs/OPERATIONS.md`.

## Backend rules

- Do not add new repo truth to `src/fx_lean_engine/`.
- Preserve the regime constants `TREND`, `CHOP`, and `RISK_OFF`.
- Keep timestamps UTC and preserve `run_id`, `schema_version`, `run_manifest.json`, and `config_snapshot.yaml` expectations.
- Keep paper/live behavior truthful: local paper artifacts are real, broker-native routing is not finished.
- Add unit tests for new behavior and integration smoke coverage when the main loop, artifacts, or run outputs change.
