# ML4T Integration Reference

This document describes the integration of algorithms and patterns from two
external ML-for-trading repositories into `fx-hybrid-engine`.

## Source Repositories (cloned to `vendor/`)

| Directory | Source | Description |
|---|---|---|
| `vendor/ml4t-jansen/` | [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | Book companion: 24 chapters, 150+ notebooks covering full ML pipeline for trading |
| `vendor/ml4t-gatech/` | [cwu392/Machine-Learning-for-Trading](https://github.com/cwu392/Machine-Learning-for-Trading) | Georgia Tech / Udacity ML4T course: StrategyLearner, DTLearner, BagLearner, indicators |

> **Note:** `vendor/` is git-ignored. Run `scripts/vendor_setup.ps1` (PowerShell) or the commands
> below to restore locally.  After cloning, run `python scripts/vendor_check.py` to verify
> directories exist and print the active commit SHAs for pinning below.

```bash
git clone --depth=1 https://github.com/stefan-jansen/machine-learning-for-trading.git vendor/ml4t-jansen
git clone --depth=1 https://github.com/cwu392/Machine-Learning-for-Trading.git vendor/ml4t-gatech
```

### Pinned commit SHAs

Record the SHA of the last tested checkout here after running `python scripts/vendor_check.py`:

| Directory | Commit SHA | Pinned date |
|---|---|---|
| `vendor/ml4t-jansen/` | _(run `python scripts/vendor_check.py` to get)_ | — |
| `vendor/ml4t-gatech/` | _(run `python scripts/vendor_check.py` to get)_ | — |

### Optional Python extras

Install the additional Python package used alongside these notebooks:

```bash
pip install -e ".[ml4t]"   # adds lightgbm>=4.0
```

---

## What Was Integrated

### 1. Advanced Technical Indicators (`src/fx_hybrid_engine/features/advanced.py`)

**Sources:**
- `vendor/ml4t-jansen/04_alpha_factor_research/` (feature engineering notebooks)
- `vendor/ml4t-gatech/strategy learner/indicators.py` and `manual_strategy/indicators_old.py`

**Indicators added:**

| Function | Description | Key params |
|---|---|---|
| `bollinger_bands(close)` | Bollinger Bands: mid, upper, lower, %B, bandwidth | `window=20`, `num_std=2.0` |
| `macd(close)` | MACD line, signal line, histogram | `fast=12`, `slow=26`, `signal_window=9` |
| `atr(high, low, close)` | Average True Range (volatility) | `window=14` |
| `stochastic(high, low, close)` | Stochastic %K and %D | `k_window=14`, `d_window=3` |
| `williams_r(high, low, close)` | Williams %R oscillator (–100 to 0) | `window=14` |
| `cci(high, low, close)` | Commodity Channel Index | `window=20` |
| `obv(close, volume)` | On-Balance Volume (cumulative) | — |
| `mfi(high, low, close, volume)` | Money Flow Index (0–100) | `window=14` |
| `compute_all_advanced(close, ...)` | All of the above in one call | optional `high`, `low`, `volume` |

**Usage:**
```python
from fx_hybrid_engine.features.advanced import compute_all_advanced

df_features = compute_all_advanced(
    close=df["close"],
    high=df["high"],
    low=df["low"],
    volume=df["volume"],
)
```

**Relevant vendor notebooks to read:**
- `vendor/ml4t-jansen/04_alpha_factor_research/01_feature_engineering.ipynb`
- `vendor/ml4t-jansen/04_alpha_factor_research/02_how_to_use_talib.ipynb`

---

### 2. Cointegration Upgrades (`src/fx_hybrid_engine/features/spread.py`)

**Sources:**
- `vendor/ml4t-jansen/09_time_series_models/05_cointegration_tests.ipynb`
- `vendor/ml4t-jansen/09_time_series_models/06_statistical_arbitrage_with_cointegrated_pairs.ipynb`
- `vendor/ml4t-jansen/04_alpha_factor_research/03_kalman_filter_and_wavelets.ipynb`

**Functions added:**

| Function | Description |
|---|---|
| `johansen_test(price_a, price_b)` | Johansen trace-statistic cointegration test (via statsmodels `coint_johansen`) |
| `kalman_spread(price_a, price_b)` | Dynamic hedge ratio via Kalman filter; returns `(spread_series, hedge_ratio_series)` |
| `half_life(spread)` | Ornstein-Uhlenbeck mean-reversion half-life in bars |

**`is_cointegrated()` now accepts `method=` parameter:**
```python
from fx_hybrid_engine.features.spread import is_cointegrated

# Use Johansen instead of default Engle-Granger:
coint, stat = is_cointegrated(price_a, price_b, method="johansen")
```

**`PairsConfig` now has `cointegration_method` field:**
```yaml
pairs:
  cointegration_method: "johansen"   # or "engle_granger" (default)
```

**Relevant vendor notebooks:**
- `vendor/ml4t-jansen/09_time_series_models/05_cointegration_tests.ipynb`
- `vendor/ml4t-jansen/09_time_series_models/07_pairs_trading_backtest.ipynb`

---

### 3. ML Ensemble Signal Engine (`src/fx_hybrid_engine/engines/ml_signal.py`)

**Sources:**
- `vendor/ml4t-jansen/11_decision_trees_random_forests/` (Random Forest for trading signals)
- `vendor/ml4t-jansen/12_gradient_boosting_machines/` (XGBoost classifiers)
- `vendor/ml4t-gatech/strategy learner/StrategyLearner.py` (BagLearner → translated to sklearn RF)

**`MLSignalEngine`** is a RandomForest + XGBoost soft-voting ensemble that generates
`LONG` / `SHORT` / `FLAT` directional signals with `confidence` scores.

```python
from fx_hybrid_engine.engines.ml_signal import MLSignalEngine
from fx_hybrid_engine.utils.config import MLSignalConfig

config = MLSignalConfig(
    n_estimators=200,
    max_depth=4,
    use_xgboost=True,
    decision_threshold=0.55,
)
engine = MLSignalEngine(config)
engine.train({"EURUSD": df_eurusd, "GBPUSD": df_gbpusd})
output = engine.generate(data, timestamp)
```

**Signal type:** `EngineType.ML_ENSEMBLE` (added to `engines/types.py`)

**Training labels:** 3-class (`DOWN`, `FLAT`, `UP`) with configurable forward-return horizon
and bps threshold.

**Feature set:** Combined basic + advanced indicators (Bollinger, MACD, ATR, etc.).
Controlled by `MLSignalConfig.use_advanced_features`.

**Model versioning:** Compatible with the existing `models/<engine>/<version>/` pattern.
Saves `ml_signal_model.joblib` + `metadata.json`.

**XGBoost is optional:** If `xgboost` is not installed, falls back to RF-only ensemble
with a warning.

**Relevant vendor notebooks:**
- `vendor/ml4t-jansen/11_decision_trees_random_forests/01_decision_trees.ipynb`
- `vendor/ml4t-jansen/12_gradient_boosting_machines/01_gradient_boosting_machines.ipynb`
- `vendor/ml4t-gatech/strategy learner/StrategyLearner.py`

---

### 4. Volatility Regime Classifier (`src/fx_hybrid_engine/regime/volatility_classifier.py`)

**Sources:**
- `vendor/ml4t-jansen/09_time_series_models/03_arch_garch_models.ipynb`

**`VolatilityRegimeClassifier`** classifies bars into `LOW_VOL`, `MED_VOL`, or `HIGH_VOL`
regimes using rolling realized-volatility percentile buckets.  Complements (does not
replace) the HMM `RegimeOrchestrator`.

```python
from fx_hybrid_engine.regime.volatility_classifier import VolatilityRegimeClassifier, VolRegime

clf = VolatilityRegimeClassifier(vol_window=20, percentile_low=33, percentile_high=67)
clf.fit(train_close)                            # calibrate thresholds
regimes = clf.classify_series(close)            # pd.Series of VolRegime
current = clf.classify_bar(recent_close)        # VolRegime.LOW | .MED | .HIGH
```

**Typical use:** Gate position size by vol regime (reduce in HIGH_VOL, increase in LOW_VOL)
in addition to the HMM regime gate.

---

### 5. Extended Evaluation Metrics (`src/fx_hybrid_engine/evaluation/metrics.py`)

**Sources:**
- `vendor/ml4t-jansen/05_strategy_evaluation/` (performance analytics notebooks)

**Functions added:**

| Function | Description |
|---|---|
| `sharpe_ratio(returns)` | Annualized Sharpe ratio |
| `sortino_ratio(returns)` | Annualized Sortino (downside deviation only) |
| `calmar_ratio(equity)` | Ann. return / max drawdown |
| `omega_ratio(returns)` | Probability-weighted gain/loss ratio |
| `information_ratio(strategy, benchmark)` | Active return / tracking error |
| `max_drawdown(equity)` | Peak-to-trough drawdown fraction |
| `max_drawdown_duration(equity)` | Longest consecutive bars in drawdown |
| `avg_trade_return(returns)` | Mean winner / loser return |
| `compute_extended_metrics(equity)` | All of the above in one dict |

> **Note:** All equity-curve functions (`max_drawdown`, `calmar_ratio`, `compute_extended_metrics`)
> expect a **wealth index** (cumulative equity, e.g., starting at 1.0 or 100.0),
> **not** a returns series.  Convert with `(1 + returns).cumprod()` if needed.

```python
from fx_hybrid_engine.evaluation.metrics import compute_extended_metrics

equity = (1 + returns).cumprod()
metrics = compute_extended_metrics(equity, benchmark_returns=bench_returns)
# metrics["sharpe"], metrics["sortino"], metrics["calmar"], ...
```

---

## Dependency Added

`xgboost>=2.0` added to `pyproject.toml` `[project] dependencies`.

---

## Key Design Constraints

- All new engines produce `EngineOutput` / `Signal` / `EngineType` objects (from `engines/types.py`).
- `MLSignalEngine` is independent of `TrendEngine`; it can run alongside or replace it.
- `VolatilityRegimeClassifier` is a lightweight stateless helper; it does NOT modify `RegimeHMM`.
- Johansen cointegration in `PairsEngine.fit()` is opt-in via `PairsConfig.cointegration_method`.
- No notebook content entered `src/`; all code is adapted/reimplemented from scratch.

---

## Further Reading in `vendor/`

| Topic | Best notebook |
|---|---|
| Pairs trading + StatArb full backtest | `vendor/ml4t-jansen/09_time_series_models/07_pairs_trading_backtest.ipynb` |
| Kalman filter for dynamic hedging | `vendor/ml4t-jansen/04_alpha_factor_research/03_kalman_filter_and_wavelets.ipynb` |
| Feature IC / factor evaluation | `vendor/ml4t-jansen/04_alpha_factor_research/06_performance_eval_alphalens.ipynb` |
| RF signal generation full example | `vendor/ml4t-jansen/11_decision_trees_random_forests/` |
| XGBoost hyperparameter tuning | `vendor/ml4t-jansen/12_gradient_boosting_machines/` |
| GARCH volatility regimes | `vendor/ml4t-jansen/09_time_series_models/03_arch_garch_models.ipynb` |
| Strategy evaluation metrics | `vendor/ml4t-jansen/05_strategy_evaluation/` |
| StrategyLearner (GT course) | `vendor/ml4t-gatech/strategy learner/StrategyLearner.py` |
| Q-learning for trading | `vendor/ml4t-gatech/qlearning_robot/` |
