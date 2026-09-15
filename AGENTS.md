# AGENTS.md - fx-hybrid-engine

## Project Reality and Current Focus

- This repository's current product is `fx-hybrid-engine`.
- The authoritative Python package is `src/fx_hybrid_engine/`.
- The active delivery focus is backend/algo work, walk-forward/proof workflows, and truthful local paper-trading plus Tastytrade groundwork.
- UI cleanup is secondary. Only trust the dashboard files called out in this document and in `ui/AGENTS.md`.
- The repository still contains `src/fx_lean_engine/` for legacy reference and migration context. Do not treat it as the current implementation surface.

## Source of Truth Priority Order

When repo files disagree, prefer them in this order:

1. `AGENTS.md`
2. `src/fx_hybrid_engine/`
3. `config/default.yaml`
4. `pyproject.toml`
5. `Makefile`
6. `docs/CONTRACTS.md`
7. `docs/OPERATIONS.md`
8. `README.md`
9. `.github/workflows/ci.yaml`

Treat these as non-authoritative unless a current repo file confirms the detail:

- `src/fx_lean_engine/`
- `config.json`
- `ui/README.md`
- starter-template branding and example pages under `ui/`

## Primary Commands from Makefile and pyproject.toml

```bash
pip install -e ".[dev]"

make test
make smoke
make lint
make format

fxhe-train --config config/default.yaml
fxhe-walkforward --config config/default.yaml
fxhe-phase1 --config config/default.yaml --profile smoke
fxhe-paper-session --config config/default.yaml --run-id demo_paper
fxhe-phase6-precheck --config config/default.yaml --run-dir outputs/paper/<YYYY-MM-DD>/<run_id>
fxhe-live-precheck --config config/default.yaml

make ai-sync
make ai-check
make ai-install
```

Prefer `make` targets when they exist. For targeted testing, use `python -m pytest tests/unit/<file>.py -q`.

## Repo Map with Current vs Legacy Package Routing

- `src/fx_hybrid_engine/`
  - Current backend: data providers, features, pairs/trend/regime engines, risk, ops, brokers, evaluation, reporting, Lean runner glue, and CLI entry points.
- `config/default.yaml`
  - Canonical trader-tunable config surface. Put tunables here instead of hard-coding thresholds.
- `tests/unit/` and `tests/integration/`
  - Fast deterministic logic tests in `unit`; end-to-end smoke and slower scenarios in `integration`.
- `ui/src/`
  - Current dashboard implementation. Artifact provenance and run-state truth are driven by:
    - `ui/src/lib/server-artifacts.ts`
    - `ui/src/lib/fx-types.ts`
    - `ui/src/app/api/state/route.ts`
    - `ui/src/app/api/run/route.ts`
    - `ui/src/config/nav-config.ts`
    - `ui/src/app/dashboard/*`
- `src/fx_lean_engine/`
  - Legacy reference only. Read for migration context if needed, but do not build new repo truth here unless a task explicitly targets the legacy surface.

## Invariants for Configs, Schemas, Artifacts, and Safety

- Keep runtime thresholds and knobs in `config/default.yaml` and the config dataclasses under `src/fx_hybrid_engine/utils/config.py`.
- Preserve the artifact contract in `docs/CONTRACTS.md`: `schema_version`, UTC timestamps, and `run_id` columns on tabular outputs.
- Runs that emit artifacts must continue to write `run_manifest.json` and `config_snapshot.yaml`.
- Use the regime constants `TREND`, `CHOP`, and `RISK_OFF`. Do not invent alternate labels.
- `Signal` and `EngineOutput` are dataclass-based interfaces. Use `dataclasses.replace(...)` instead of ad hoc mutation patterns when adjusting signals.
- Do not hard-code broker, rail, or paper/live safety thresholds in code when they belong in config.
- If an artifact schema changes, update validators, docs, and the corresponding tests in the same change.
- Add at least one unit test for new backend behavior. Add or update an integration smoke test when the main loop, artifacts, or run outputs change.

## Current Ops Truth for Tastytrade Local Paper vs Broker-Native Not-Yet-Real

- The local paper workflow is real and currently emits truthful paper artifacts such as `paper_trades.json`, `paper_position_plan.json`, `paper_strategy_summary.json`, and `paper_safety_summary.json`.
- Broker-aware plumbing for Tastytrade exists for credentials, account data, positions, and live-order inspection.
- The current Tastytrade path is still local paper plus broker-aware validation. It is not broker-native routing yet.
- Exact FX-to-futures contract mapping, roll handling, broker-native order submission, and broker-native market-data ingestion remain unfinished.
- Never describe the current paper workflow as broker-routed paper trading or live trading.
- Never persist or reuse secrets pasted in chat. If credentials were exposed, call out rotation explicitly and avoid writing them anywhere.

## Role Routing Matrix

| Role | Use when | Primary ownership | Required output |
| --- | --- | --- | --- |
| `fxhy-architect` | A request is ambiguous, cross-cutting, multi-phase, or needs a concrete handoff before code work starts | Scope, source-of-truth routing, owner selection, risks, validation plan | Goal, current state, primary executor, likely files, validation commands, blockers |
| `fxhy-quant-engineer` | Work is centered in `src/fx_hybrid_engine/data`, `features`, `engines`, `regime`, `risk`, `portfolio`, `evaluation`, or config/CLI surfaces that change backend behavior | Backend algo and config work | Code change plus tests, config/doc updates as needed |
| `fxhy-ops-broker` | Work is centered in brokers, paper/live rails, prechecks, artifact truthfulness, promotion logic, or dashboard behavior driven by run-state artifacts | Ops, broker, paper/live, Lean/QC, artifact truthfulness | Safe behavior change plus validation for the affected run path |
| `fxhy-review-validator` | A task is ready for review, final validation, or release gating | Review, regression detection, docs/contracts sync, final acceptance | Findings first, residual risks, and validation status |

Use `fxhy-architect` first for any unclear or cross-domain task. Route implementation to exactly one primary executor: `fxhy-quant-engineer` or `fxhy-ops-broker`. Finish every non-trivial task with `fxhy-review-validator`.

## Required Validation Rules

- Backend logic changes: run the smallest targeted unit tests first, then broaden to `make test` if multiple modules or contracts moved.
- Main-loop or artifact changes: run the relevant smoke or contract command, such as `make smoke`, `fxhe-validate-run`, `fxhe-phase6-precheck`, or `fxhe-live-precheck`.
- Broker and paper/live changes: verify that local paper is still described truthfully and that no broker-native behavior is implied without backend support.
- Config or behavior changes: update `README.md` and any affected docs in the same change.
- AGENTS, skills, or repo agent tooling changes: run `make ai-sync` and `make ai-check`.

## Doc and Skill Sync Protocol

- Edit `AGENTS.md` for shared repo-wide guidance.
- Treat `.github/copilot-instructions.md` as generated output. Do not edit it directly.
- Use the folder index `README.md` files in `docs/`, `skills/`, `skills/public/`, `scripts/`, `src/`, `config/`, `tests/`, and `ui/` as navigation layers for future recall.
- Keep repo-tracked skills under `skills/public/`.
- Keep `skills/public/<role>/README.md`, `SKILL.md`, and `agents/openai.yaml` aligned so the human-facing folder guide and the role contract do not drift.
- Keep scoped `AGENTS.md` files focused on repo truth and link out to folder guides or secondary docs instead of carrying long template or vendor guidance.
- The current repo-tracked skills are:
  - `skills/public/fxhy-architect/`
  - `skills/public/fxhy-quant-engineer/`
  - `skills/public/fxhy-ops-broker/`
  - `skills/public/fxhy-review-validator/`
- After changing `AGENTS.md`, run `make ai-sync`.
- After changing any AGENTS file, skill, or agent-tooling script, run `make ai-check`.
- Install or refresh the repo skills in the local Codex skill directory with `make ai-install`.

## Codex and GitHub Workflow Notes

- Contributor workflow details live in `docs/DEVELOPER.md`. Keep that file aligned with this root contract.
- `make ai-install` installs repo skills into `~/.codex/skills` by default, or into `$CODEX_HOME/skills` when `CODEX_HOME` is set. The install script copies on Windows and symlinks elsewhere unless explicitly overridden.
- Use the role routing matrix above to choose the right Codex role before implementation. Use `fxhy-architect` for ambiguity and finish non-trivial work with `fxhy-review-validator`.
- Prefer the existing repo branch convention. The current repo commonly uses `work` as the integration branch and `codex/*` for focused agent branches.
- Prefer GitHub CLI for PR and CI follow-up when available, for example `gh pr create --fill --base work`, `gh pr status`, and `gh run view --log-failed`.
- The PowerShell helper `scripts/export_for_copilot.ps1` is a repo-specific fallback for exporting `origin/work..work` commits into a pending patch for Copilot. Document workflow changes against that script carefully before relying on it more broadly.
