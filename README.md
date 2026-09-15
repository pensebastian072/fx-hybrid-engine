# fx-hybrid-engine

A hybrid quantitative FX trading system combining:

- **Pairs (StatArb) Engine** — cointegration-based mean-reversion on currency pairs
- **Trend Engine** — logistic-regression classifier on momentum/technical features
- **HMM Regime Orchestrator** — 3-state Hidden Markov Model (Trend / Chop / Risk-Off) that gates which engine is active

Data ingestion uses a provider abstraction (`openbb`, `lean_history`, `oanda` stub) with a unified bar schema.  
Backtesting stays on the **Lean / QuantConnect** stack, while live-precheck and ops metadata can now target either the legacy QC rail or a Tastytrade rail.

Canonical Phase 1 cadence is **15m intraday** (`data.bar_frequency: "15m"`).

## Quick Start

```bash
pip install -e ".[dev]"

# Train all models (HMM + trend LogReg)
fxhe-train --config config/default.yaml

# Run a Lean backtest
fxhe-backtest --config config/default.yaml --start 2020-01-01 --end 2023-12-31

# Phase 5 walk-forward proof bundle (local deterministic default)
fxhe-walkforward --config config/default.yaml

# Optional standalone regime comparison (hmm vs heuristic vs none)
fxhe-regime-compare --config config/default.yaml --max-splits 1

# Phase 1 verification runner (smoke profile)
fxhe-phase1 --config config/default.yaml --profile smoke

# Build a trend training dataset artifact
fxhe-build-trend-dataset --config config/default.yaml

# Train a versioned trend model artifact
fxhe-train-trend --config config/default.yaml

# Validate artifact contract for a completed run
fxhe-validate-run --run-dir artifacts/walkforward/<wf_run_id>

# Regenerate report from an existing run
fxhe-report --config config/default.yaml --wf-run-id <wf_run_id>

# Verify parity between optimized and fallback runs
fxhe-verify-parity --run-a artifacts/walkforward/<run_a> --run-b artifacts/walkforward/<run_b> --profile local_smoke

# Bootstrap a paper-session run directory
fxhe-paper-session --config config/default.yaml --run-id demo_paper

# Run strict Phase 6 completion precheck
fxhe-phase6-precheck --config config/default.yaml --run-dir outputs/paper/<YYYY-MM-DD>/<run_id>

# Run weekly eval (walk-forward + decision.json)
fxhe-weekly-eval --config config/default.yaml

# Run promotion decision check from proof + paper telemetry
fxhe-promote-check --config config/default.yaml --wf-id <wf_run_id> --paper-run-dir outputs/paper/<YYYY-MM-DD>/<run_id>

# Run live deployment precheck (fails fast on unsafe config/env)
fxhe-live-precheck --config config/default.yaml

# To evaluate a Tastytrade live rail, switch `live_execution.broker` / `live_execution.rail`
# in config and provide the Tastytrade OAuth env vars plus symbol_map first.
# If `live_execution.rail=tastytrade_live`, explicitly set
# `live_execution.enable_broker_native_orders=true` and
# `live_execution.enable_broker_market_data=true`.
# Broker-native runs also emit `broker_native_summary.json` for provenance.
# The current paper rail stays honest by writing local-paper snapshots such as
# `paper_trades.json`, `paper_position_plan.json`, and `paper_safety_summary.json`
# before any broker-native routing is enabled.
fxhe-live-precheck --config config/default.yaml

# Start the configured live rail
fxhe-live --config config/default.yaml --paper

# Developer shortcuts
make smoke
make phase1
make validate RUN_DIR=artifacts/walkforward/<wf_run_id>

# End-to-end local pipeline (train + walkforward + paper bootstrap + precheck)
powershell -ExecutionPolicy Bypass -File .\run_algo.ps1

# Include QC gates
powershell -ExecutionPolicy Bypass -File .\run_algo.ps1 -RunLivePrecheck -PushQCPaper

# Inspect regime state on recent data
fxhe-regime --config config/default.yaml --symbol EURUSD

# Paper trade (Lean paper account)
fxhe-live --config config/default.yaml --paper
```

## AI / Contributor Workflow

- Root `AGENTS.md` is the canonical agent and contributor contract for this repo.
- Contributor setup, Codex skill usage, branch flow, patch export, and GitHub CLI examples live in [docs/DEVELOPER.md](docs/DEVELOPER.md).
- Use the 4 repo roles to keep work scoped:
  - `fxhy-architect` for planning and routing
  - `fxhy-quant-engineer` for backend/algo changes
  - `fxhy-ops-broker` for paper/live/broker and artifact-truthfulness changes
  - `fxhy-review-validator` for final review and acceptance
- The repo-tracked Codex skills live under `skills/public/` with matching names:
  - `fxhy-architect`
  - `fxhy-quant-engineer`
  - `fxhy-ops-broker`
  - `fxhy-review-validator`
- Install and refresh the repo-tracked Codex skills with `make ai-install`.
- Regenerate the GitHub Copilot instructions from root `AGENTS.md` with `make ai-sync`.
- Validate the agent system and repo skills with `make ai-check`.
- For UI work, read `ui/AGENTS.md` after the root file.
- For package-specific backend work, read `src/fx_hybrid_engine/AGENTS.md` after the root file.
- Recommended contributor tools for this workflow are `codex` and `gh`, but the repo commands still work with plain git if needed.
- Quick contributor checks:

```bash
make ai-install
make lint
make test
gh pr status
```

- Folder guides for faster recall:
  - [`docs/README.md`](docs/README.md) — contracts, operations, and contributor docs
  - [`skills/README.md`](skills/README.md) — repo-tracked skill system overview
  - [`skills/public/README.md`](skills/public/README.md) — 4-role catalog and folder layout
  - [`scripts/README.md`](scripts/README.md) — workflow and helper script map
  - [`src/README.md`](src/README.md) — current vs legacy source surfaces
  - [`config/README.md`](config/README.md) — canonical config entry points
  - [`tests/README.md`](tests/README.md) — validation layout and test commands
  - [`ui/README.md`](ui/README.md) — dashboard-specific folder guide
- Each repo role folder under `skills/public/<role>/` also carries its own `README.md` paired with `SKILL.md`.
- Treat `src/fx_hybrid_engine/`, `config/default.yaml`, `docs/CONTRACTS.md`, and `docs/OPERATIONS.md` as the current repo truth.
- Treat `src/fx_lean_engine/` as legacy reference only.
- Current ops reality: local Tastytrade paper artifacts are real, but broker-native routing and exact FX-futures contract mapping are still unfinished. Do not describe the current paper path as broker-routed paper/live trading.

## Project Structure

```
src/fx_hybrid_engine/
  data/          - provider abstraction, cadence validation, bar normalization/health, feature store
    providers/   - OpenBB, Lean history, OANDA stub, factory
  features/      - indicators (SMA, EMA, RSI, vol, momentum) and spread/z-score
  engines/       - pairs (StatArb) and trend (LogReg) signal engines
  regime/        - GaussianHMM trainer, state inference, orchestrator
  risk/          - position sizing, stop-loss, drawdown kill-switch
  portfolio/     - signal aggregation → target weights
  lean/          - QCAlgorithm wrapper + Lean CLI runner
  backtest/      - parameter sweep runner
  reporting/     - Sharpe, drawdown, per-regime PnL attribution
config/
  default.yaml   - all trader-tunable parameters
tests/
  unit/          - per-module unit tests
  integration/   - end-to-end mixed-regime simulation
```

## Trader-Tunable Parameters

See [`config/default.yaml`](config/default.yaml) for all parameters:
- Symbol universe, pair candidates
- Cointegration p-value threshold, z-score entry/exit levels
- Trend model lookback, signal confidence threshold, MA windows
- HMM observation window, model paths
- Risk: max leverage, stop-loss %, drawdown kill-switch %
- Walk-forward windows, artifact output root, backend/data profile
- Data source (`openbb|lean_history|oanda`) and canonical bar frequency (`15m`)
- Pair scan/state thresholds (`pairs_policy`)
- Regime QA thresholds (`regime_qa`) and comparison policy controls (`regime_compare`)
- Execution costs/slippage assumptions
- Robustness sweep scenarios and perturbation ranges
- Phase 5 proof gate thresholds
- Ops health/reconciliation/circuit-breakers
- Micro-live ladder stages and multipliers
- Live execution rail selection (`live_execution`) and Tastytrade OAuth + symbol-map settings (`tastytrade`)
- Weekly evaluation profile + model registry + alerts

## Phase 5 Artifacts

Each `fxhe-walkforward` run produces:

```
artifacts/walkforward/<wf_run_id>/
  run_manifest.json
  splits.csv
  metrics_by_split.csv
  pnl_attribution_engine.csv
  pnl_attribution_regime.csv
  pnl_attribution_engine_x_regime.csv
  pairs_diagnostics_by_split.csv
  regime_qa_by_split.csv
  regime_comparison_metrics.csv                # when enabled
  regime_comparison_report.md                  # when enabled
  robustness_cost_sweep.csv
  robustness_param_sweep.csv
  proof_checks.json
  phase5_proof_report.md
  phase5_report_summary.json
  split_000/
    pairs_candidates.csv
    pairs_scan.csv
    pairs_diagnostics.csv
    pair_state_events.csv
    pair_state_snapshot.json
    regime_events.csv
    regime_summary.json
    hmm_state_map.json
    hybrid|pairs_only|trend_only/
      signals.csv
      trades.csv
      fills.csv
      equity_curve.csv
      metrics.json
      config_snapshot.yaml
      regime_posteriors.csv
      engine_allocations.csv
```

`metrics_by_split.csv` includes runtime traceability columns:
- `precompute_enabled`
- `mode_reuse_enabled`
- `cache_fingerprint`
- `pipeline_version`

## Run Manifest Contract

Each walk-forward root includes `run_manifest.json` for reproducibility and audit:

- `wf_run_id`
- `created_at_utc`
- `config_path`
- `git_commit` (`"unknown"` fallback outside git metadata)
- `config_hash` (sha256 canonical config hash)
- `schema_version`
- `seed`
- `precompute_enabled`
- `mode_reuse_enabled`
- `skip_robustness`
- `data_profile`
- `symbols`
- `pair_list`
- `trend_symbols`
- `split_params`
- `cost_params`
- `cache_fingerprint`
- `pipeline_version`

`cache_fingerprint` is computed as `sha256(json.dumps(payload, sort_keys=True))` using strategy/data/split/cost inputs.

`config_hash` is computed as `sha256` over canonical sorted JSON config payload.

## Stage 4 Trend Model Artifacts

`fxhe-train-trend` writes:

```
models/trend/<model_version>/
  trend_model.joblib
  metadata.json
  metrics_by_split.csv
  oos_summary.json
```

`metadata.json` includes `feature_schema_hash` and `feature_columns`.
`TrendEngine.load_model_version(...)` validates both before loading.

## Contracts

Canonical contracts and schema versioning:
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md)
- [`docs/TREND_FEATURE_CONTRACT.md`](docs/TREND_FEATURE_CONTRACT.md)

## Operations

Phase 6 ops bootstrap documentation:
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md)

## Phase 6 Output Layout

Canonical new layout:

```
outputs/<mode>/<YYYY-MM-DD>/<run_id>/
```

Legacy compatibility (still accepted by precheck):

```
artifacts/ops/<run_id>/
```

Phase 6 strict precheck reports:
- `phase6_precheck_report.json`
- `phase6_precheck.md`

Tastytrade paper runs also emit helper snapshots in each run directory:
- `paper_trades.json`
- `paper_position_plan.json`
- `paper_strategy_summary.json`
- `paper_safety_summary.json`

## Dashboard UI

A local Next.js dashboard for monitoring algo runs without live trading.

### Stack
- **Framework**: Next.js 16 (App Router) + TypeScript
- **UI kit**: shadcn/ui (Radix) + Tailwind CSS v4
- **Charts**: lightweight-charts (price/OHLCV) · recharts (equity curve)
- **Base template**: [Kiranism/next-shadcn-dashboard-starter](https://github.com/Kiranism/next-shadcn-dashboard-starter) (MIT)

### Quick Start

```bash
cd ui
npm install
npm run dev
# Open http://localhost:3000
```

Redirects automatically to `/dashboard/algo`.

### How Artifacts Are Loaded

`GET /api/state` resolves artifacts in priority order:

1. `artifacts/latest_run/` — produced by `scripts/normalize_artifacts.py` after each algo run
2. `artifacts/mock/` — static sample data (always present; used when no run has occurred)

### Run Algo from UI

Navigate to **Settings** (`/dashboard/settings`), configure params, and click **Run Algo**.  
This calls `POST /api/run`, which spawns `run_algo.ps1` and streams output to the log panel.  
After the run completes, the normalizer writes to `artifacts/latest_run/`.  
Click **Refresh** on the dashboard to reload the new state.

### Normalize Artifacts Manually

```bash
python scripts/normalize_artifacts.py
# Optional: point at specific runs
python scripts/normalize_artifacts.py --wf-run-id wf_20260303_204951 --paper-run-dir outputs/paper/2026-03-04/paper_20260303_204951
```

### Artifact Schema (`artifacts/latest_run/`)

| File | Description |
|------|-------------|
| `manifest.json` | Run metadata: `run_id`, `started_at`, `regime`, `errors[]`, `warnings[]`, `notes[]`, `metrics` |
| `trades.json` | Array of trades: `time`, `symbol`, `side`, `entry`, `exit`, `pnl`, `close_reason`, `tags[]` |
| `candles.json` | OHLCV bars: `time`, `open`, `high`, `low`, `close`, `volume` |
| `equity_curve.json` | Equity over time: `timestamp`, `equity`, `regime_label` |
| `run.log` | Raw stdout/stderr from last `run_algo.ps1` invocation (optional) |
