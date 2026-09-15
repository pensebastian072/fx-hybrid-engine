# Contracts

This repository uses a canonical schema contract version:

- `schema_version`: `1.0.0`

The version is written into run manifests so artifacts can be validated and replayed consistently across backtest, walk-forward, and paper-session outputs.

## BarSchema

Required columns:

- `timestamp`
- `symbol`
- `open`
- `high`
- `low`
- `close`
- `run_id`

## FeatureSchema

Required columns:

- `timestamp`
- `symbol`
- `run_id`

## SignalSchema

Required columns:

- `timestamp`
- `symbol`
- `engine_source`
- `run_id`

## OrderSchema

Required columns:

- `timestamp`
- `symbol`
- `order_type`
- `run_id`

## FillSchema

Required columns:

- `timestamp`
- `symbol`
- `run_id`

## ArtifactsSchema

Walk-forward root minimum:

- `run_manifest.json`
- `splits.csv`
- `metrics_by_split.csv`

Ops/paper minimum streams:

- `bars.parquet`
- `features.parquet`
- `signals.parquet`
- `targets.parquet`
- `orders.parquet`
- `fills.parquet`
- `equity_curve.parquet`
- `risk_events.parquet`
- `broker_events.jsonl`
- `reconciliation_events.jsonl`
- `run_manifest.json`
- `config_snapshot.yaml`
- `ops_summary.json`

Ops/paper snapshot minimum:

- `paper_safety_summary.json`

## Manifest Fields

All manifests must include:

- `git_commit` (`"unknown"` fallback when `.git` metadata is unavailable)
- `config_hash` (sha256 over canonical sorted JSON config)
- `schema_version`
- `seed`

## Reconciliation Contract (Paper/Ops)

`paper_safety_summary.json` must carry explicit reconciliation provenance fields:

- `reconciliation_mode` in `{ "broker_validated", "simulated", "skipped" }`
- `reconciliation_status` as a non-empty status string
- `reconciliation_reason` when mode is `skipped` or otherwise explanatory

`reconciliation_events.jsonl` records should include:

- `reconciliation_mode`
- `reconciliation_status`
- `reconciliation_reason` (when applicable)
- `resolved`

For local paper, skipped reconciliation is valid when broker state is unavailable and must be explicit. It must not be implied as broker-native reconciliation.

## Trend Model Artifact Metadata

Versioned Stage 4 trend artifacts (`models/trend/<version>/metadata.json`) must include:

- `feature_schema_hash`
- `feature_columns`
- `label_mode`
- `label_horizon_bars`
- `label_threshold_bps`
