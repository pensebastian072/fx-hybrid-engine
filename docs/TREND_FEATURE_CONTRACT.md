# Trend Feature Contract

Canonical trend feature builder:

- Module: `src/fx_hybrid_engine/engines/trend_features.py`
- Function: `compute_trend_features(close, cfg) -> DataFrame`

This contract is shared by:

- Stage 4 dataset/training pipeline
- `TrendEngine` live/backtest inference

## Feature Columns

Required model input columns (`feature_columns(cfg)`):

1. `log_return`
2. `sma_crossover`
3. `rsi`
4. `realized_vol`
5. `momentum_slope`

## Lookback Inputs

The schema hash depends on:

1. `feature_lookback`
2. `sma_fast`
3. `sma_slow`
4. ordered feature column list
5. contract version tag (`trend_features_v1`)

## Leakage Rules

1. Features at timestamp `t` use data up to `t` only.
2. Labels use forward return over `label_horizon_bars`:
   `forward_return[t] = close[t + H] / close[t] - 1`
3. Binary label:
   `label = 1 if forward_return > label_threshold_bps / 10000 else 0`
4. Rows with missing feature values or missing forward returns are dropped before training.

## Schema Compatibility

Versioned trend model artifacts store:

1. `feature_schema_hash`
2. `feature_columns`

`TrendEngine.load_model_version(...)` validates both against current runtime config.
If mismatch is detected, model loading fails fast with an explicit error.
