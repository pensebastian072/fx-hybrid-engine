# Developer Workflow

This document explains how to contribute to `fx-hybrid-engine` using the repo's Codex skills, local validation commands, and GitHub CLI workflow.

Start with [AGENTS.md](../AGENTS.md). For UI work, also read [ui/AGENTS.md](../ui/AGENTS.md). For package-specific backend work, read [src/fx_hybrid_engine/AGENTS.md](../src/fx_hybrid_engine/AGENTS.md).

## Folder Navigation For Recall

Use these folder guides when you are returning to the repo, handing work between chats, or trying to remember where a workflow lives:

- [docs/README.md](./README.md) — index for contributor, contract, and operations docs
- [skills/README.md](../skills/README.md) — top-level skill system overview
- [skills/public/README.md](../skills/public/README.md) — role catalog and shared skill folder layout
- [scripts/README.md](../scripts/README.md) — workflow-supporting scripts and validation helpers
- [src/README.md](../src/README.md) — current vs legacy source tree map
- [config/README.md](../config/README.md) — canonical configuration surfaces
- [tests/README.md](../tests/README.md) — test layout and commands
- [ui/README.md](../ui/README.md) — dashboard-specific folder guide

## Local Setup

```bash
pip install -e ".[dev]"

make lint
make test
```

Optional extras:

```bash
pip install -e ".[lean]"
pip install -e ".[ml4t]"
```

Recommended local tools for the workflow described here:

- `codex` for Codex CLI / repo skill execution
- `gh` for pull requests, branch inspection, and CI follow-up

If either tool is unavailable on your machine, you can still work with normal git and the repo `make` targets.

## Source Of Truth

Use the docs in this order when contributor guidance disagrees:

1. [AGENTS.md](../AGENTS.md)
2. [src/fx_hybrid_engine/](../src/fx_hybrid_engine/)
3. [config/default.yaml](../config/default.yaml)
4. [pyproject.toml](../pyproject.toml)
5. [Makefile](../Makefile)
6. [docs/CONTRACTS.md](./CONTRACTS.md)
7. [docs/OPERATIONS.md](./OPERATIONS.md)
8. [README.md](../README.md)

Treat [src/fx_lean_engine/](../src/fx_lean_engine/) as legacy reference only unless the task explicitly targets it.

## Codex Roles And Repo Skills

The repo uses four scoped roles. The skill directories live under [skills/public/](../skills/public/).

Each role folder pairs a human-facing `README.md` with the executable role contract in `SKILL.md` and the CLI-facing descriptor in `agents/openai.yaml`.

- `fxhy-architect` → [skills/public/fxhy-architect/](../skills/public/fxhy-architect/): planning, routing, and validation briefs for ambiguous or cross-cutting work
- `fxhy-quant-engineer` → [skills/public/fxhy-quant-engineer/](../skills/public/fxhy-quant-engineer/): backend algo, config, and evaluation work in `src/fx_hybrid_engine/`
- `fxhy-ops-broker` → [skills/public/fxhy-ops-broker/](../skills/public/fxhy-ops-broker/): paper/live rails, broker-aware flows, and artifact-truthfulness work
- `fxhy-review-validator` → [skills/public/fxhy-review-validator/](../skills/public/fxhy-review-validator/): findings-first review, validation, and release gating

Use `fxhy-architect` first when the request is unclear or spans multiple domains. Finish non-trivial work with `fxhy-review-validator`.

## Codex Skill Lifecycle

Install the repo skills locally:

```bash
make ai-install
```

What it does:

- installs skills from [skills/public/](../skills/public/) into `~/.codex/skills` by default
- uses `$CODEX_HOME/skills` instead if `CODEX_HOME` is set
- uses copy mode on Windows and symlink mode elsewhere unless you override the script directly
- records the install in a `.fxhy-repo-skills.json` manifest in the target skills directory

Validate repo agent files and skill definitions:

```bash
make ai-check
```

Regenerate the Copilot instructions mirror after changing root [AGENTS.md](../AGENTS.md):

```bash
make ai-sync
make ai-check
```

Use `make ai-check` after changing any AGENTS file, skill file, or agent-tooling script. Use `make ai-sync` only when root [AGENTS.md](../AGENTS.md) changed.

## Validation Commands

Prefer the smallest repo-native command that proves the change.

Core commands:

```bash
make lint
make test
make smoke
```

Targeted examples:

```bash
python -m pytest tests/unit/<file>.py -q
fxhe-walkforward --config config/default.yaml
fxhe-paper-session --config config/default.yaml --run-id demo_paper
fxhe-phase6-precheck --config config/default.yaml --run-dir outputs/paper/<YYYY-MM-DD>/<run_id>
fxhe-live-precheck --config config/default.yaml
```

Rules of thumb:

- backend logic changes: targeted unit tests first, then broaden only if needed
- main-loop or artifact changes: run smoke or artifact validation commands
- AGENTS / skills / tooling changes: `make ai-sync` when root AGENTS changes, then `make ai-check`
- UI changes driven by backend artifacts: validate the backend truth and the UI contract together

## Branch And Patch Workflow

The repo currently uses `work` as the shared integration branch, and focused agent branches may use a `codex/*` naming pattern. Follow the team convention already present in the repository instead of inventing a new branch model.

Typical branch flow:

```bash
git switch work
git pull --ff-only origin work
git switch -c codex/<short-task-name>
```

If you use GitHub CLI, a practical PR flow is:

```bash
gh repo view --web
gh pr create --fill --base work
gh pr status
```

Useful CI follow-up commands:

```bash
gh run list --limit 5
gh run view --log-failed
gh pr checks
```

## Codex Patch Export Fallback

Windows fallback script: [scripts/export_for_copilot.ps1](../scripts/export_for_copilot.ps1)

```powershell
powershell -File scripts\export_for_copilot.ps1
```

This is a repo-specific fallback for exporting commits from `origin/work..work` into `~/.copilot/pending_patch.patch` so Copilot can apply and push them later.

Use it only when the normal local git push / PR flow is blocked. The script assumes the current repo remote and branch model; review it before using it in a different clone layout.

## Suggested End-To-End Contributor Flow

1. Read [AGENTS.md](../AGENTS.md) and the nearest scoped AGENTS file.
2. Pick the correct Codex role for the task.
3. Install or refresh repo skills with `make ai-install` if your local skill registry is stale.
4. Implement the change in the current source-of-truth surface.
5. Run the smallest validation command set that proves the change.
6. If you changed root AGENTS, run `make ai-sync` and then `make ai-check`.
7. Open or update a PR, preferably with `gh`, and inspect CI before merge.
8. For reviews or final acceptance, use the `fxhy-review-validator` role.

## Common Pitfalls

- Do not edit [.github/copilot-instructions.md](../.github/copilot-instructions.md) directly. It is generated.
- Do not add new repo truth to [src/fx_lean_engine/](../src/fx_lean_engine/).
- Do not describe the current Tastytrade paper flow as broker-native routing or live trading.
- Do not skip [ui/AGENTS.md](../ui/AGENTS.md) when changing dashboard provenance or run-state semantics.
