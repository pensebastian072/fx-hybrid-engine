# Source Tree

Use this folder guide to remember which package is current and which one is legacy.

## Read First

1. [`../AGENTS.md`](../AGENTS.md)
2. [`../docs/DEVELOPER.md`](../docs/DEVELOPER.md)
3. This README

## Current Vs Legacy

- [`fx_hybrid_engine/`](fx_hybrid_engine/) — current authoritative backend package for this repository
- [`fx_lean_engine/`](fx_lean_engine/) — legacy reference code only

## Workflow Notes

- New repo truth belongs in `fx_hybrid_engine/`, not `fx_lean_engine/`, unless the task explicitly targets the legacy surface.
- Use the folder-specific guides in each package to get back to the right implementation surface quickly.
