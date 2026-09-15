# Tests

This folder contains the repo's automated validation surfaces.

## Read First

1. [`../AGENTS.md`](../AGENTS.md)
2. [`../docs/DEVELOPER.md`](../docs/DEVELOPER.md)
3. This README

## Layout

- `unit/` — fast deterministic tests for specific modules and tooling
- `integration/` — broader end-to-end or smoke-style validation

## Common Commands

- `python -m pytest tests\unit\<file>.py -q`
- `python -m pytest tests\unit\test_agent_system.py -q`
- `python -m pytest tests\integration -q -m "integration and not slow"`
- `make test`
- `make smoke`

## Workflow Notes

- Start with the smallest targeted test that proves the change.
- Broaden only when artifact contracts, main loops, or cross-cutting workflow surfaces changed.
