# Repo-Tracked Skills

This folder is the top-level home for the repo's reusable Copilot and Codex skill definitions.

## Read First

1. [`../AGENTS.md`](../AGENTS.md)
2. [`../docs/DEVELOPER.md`](../docs/DEVELOPER.md)
3. [`public/README.md`](public/README.md)

## What Lives Here

- [`public/`](public/) — the four repo-tracked role folders used for planning, implementation, ops/broker work, and review

## Workflow Notes

- Each role folder in `public/` carries:
  - `README.md` for human-facing navigation and recall
  - `SKILL.md` for the role contract
  - `agents/openai.yaml` for the CLI-facing descriptor
- On Windows, the install flow copies repo skills into the target registry by default. On non-Windows systems, the install flow prefers symlinks unless overridden.
- Keep the role readmes, skill files, and validation rules aligned so the same workflow works across future chats and local setups.

## Common Commands

- Prefer `make ai-install` and `make ai-check` when available.
- Direct script equivalents:
  - `python scripts\install_repo_skills.py --mode auto`
  - `python scripts\validate_repo_skills.py`
