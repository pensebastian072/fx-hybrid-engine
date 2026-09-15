"""Phase 1 verification runner (data loop + artifacts)."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fx_hybrid_engine.contracts import SCHEMA_VERSION
from fx_hybrid_engine.data.alignment import normalize_universe
from fx_hybrid_engine.data.provider import fetch_multi_symbol
from fx_hybrid_engine.engines.pairs import PairsEngine
from fx_hybrid_engine.engines.trend import TrendEngine
from fx_hybrid_engine.evaluation.local_backtester import run_local_backtest
from fx_hybrid_engine.features.indicators import compute_all, momentum_slope, rolling_vol
from fx_hybrid_engine.ops.layout import build_run_dir
from fx_hybrid_engine.ops.storage import (
    append_bars,
    append_broker_events,
    append_equity_curve,
    append_features,
    append_fills,
    append_orders,
    append_reconciliation_events,
    append_risk_events,
    append_signals,
    append_targets,
    initialize_run_metadata,
)
from fx_hybrid_engine.regime.hmm import RegimeHMM
from fx_hybrid_engine.regime.orchestrator import RegimeOrchestrator
from fx_hybrid_engine.utils.config import EngineConfig, load_config
from fx_hybrid_engine.utils.identity import hash_config, make_run_id, resolve_git_commit


def _profile_dates(profile: str) -> tuple[str, str]:
    if profile == "smoke":
        return ("2024-01-01", "2024-01-03")
    if profile == "verification":
        return ("2022-01-01", "2024-01-01")
    raise ValueError("Unsupported profile. Use smoke or verification.")


def _profile_symbols(cfg: EngineConfig, profile: str) -> list[str]:
    if profile == "smoke":
        if cfg.trend_symbols:
            return [cfg.trend_symbols[0]]
        if cfg.pair_list:
            return [cfg.pair_list[0][0]]
        raise ValueError("No symbols configured for smoke profile")
    return sorted(list({s for pair in cfg.pair_list for s in pair} | set(cfg.trend_symbols)))


def _fit_hmm_from_training(cfg: EngineConfig, train_data: dict[str, pd.DataFrame]) -> RegimeHMM | None:
    obs: list[np.ndarray] = []
    for df in train_data.values():
        if "close" not in df.columns or len(df) < cfg.regime.vol_window + 2:
            continue
        vol = rolling_vol(df["close"], window=cfg.regime.vol_window, annualize=True)
        mom = momentum_slope(df["close"], window=cfg.regime.vol_window)
        combined = pd.DataFrame({"vol": vol, "mom": mom}).dropna()
        if len(combined):
            obs.append(combined.values)
    if not obs:
        return None
    hmm = RegimeHMM(n_states=cfg.regime.n_states)
    hmm.fit(np.vstack(obs))
    return hmm


def _train_trend_safely(cfg: EngineConfig, engine: TrendEngine, train_data: dict[str, pd.DataFrame]) -> None:
    required = cfg.trend.sma_slow + cfg.trend.feature_lookback + 10
    eligible = {k: v for k, v in train_data.items() if "close" in v.columns and len(v) >= required}
    if not eligible:
        return
    try:
        engine.train(eligible)
    except Exception:  # noqa: BLE001
        # keep fallback model path
        return


def _long_bars(symbol_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for symbol, df in symbol_data.items():
        frame = df.copy().reset_index().rename(columns={"index": "timestamp"})
        frame["symbol"] = symbol
        rows.append(frame[["timestamp", "symbol", "open", "high", "low", "close", "volume"]])
    if not rows:
        return pd.DataFrame(columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"])
    return pd.concat(rows, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def _features_from_bars(symbol_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for symbol, df in symbol_data.items():
        if "close" not in df.columns:
            continue
        feats = compute_all(df["close"], sma_fast=20, sma_slow=60).copy()
        feats = feats.reset_index().rename(columns={"index": "timestamp"})
        feats["symbol"] = symbol
        rows.append(feats)
    if not rows:
        return pd.DataFrame(columns=["timestamp", "symbol"])
    return pd.concat(rows, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def run_phase1(
    *,
    config_path: str | Path = "config/default.yaml",
    profile: str = "smoke",
    run_id: str | None = None,
) -> Path:
    """Run Phase 1 data-loop verification and write append-only artifacts."""
    cfg = load_config(config_path)
    start, end = _profile_dates(profile)
    symbols = _profile_symbols(cfg, profile)

    raw = fetch_multi_symbol(
        symbols=symbols,
        start=start,
        end=end,
        provider=cfg.data.openbb_provider,
        frequency=cfg.data.bar_frequency,
        source=cfg.data.source,
        seed=cfg.robustness.random_seed,
    )
    if not raw:
        raise RuntimeError("No bars returned from configured provider")
    aligned, bar_health = normalize_universe(raw, target_frequency=cfg.data.bar_frequency)
    if not aligned:
        raise RuntimeError("No aligned bars after normalization")

    cfg_payload = asdict(cfg)
    config_hash = hash_config(cfg_payload)
    now = datetime.now(UTC)
    effective_run_id = run_id or make_run_id(now, config_hash)
    run_dir = build_run_dir(cfg.ops.output_root, mode="phase1", run_id=effective_run_id, run_date_utc=now)
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": effective_run_id,
        "profile": profile,
        "config_path": str(Path(config_path).resolve()),
        "git_commit": resolve_git_commit(),
        "config_hash": config_hash,
        "schema_version": SCHEMA_VERSION,
        "seed": int(cfg.robustness.random_seed),
        "data_source": cfg.data.source,
        "bar_frequency": cfg.data.bar_frequency,
        "symbols": symbols,
        "start_date": start,
        "end_date": end,
        "runtime_toggles": {"precompute_enabled": None, "mode_reuse_enabled": None},
    }
    initialize_run_metadata(run_dir, run_manifest=manifest, config_snapshot={"config": cfg_payload})

    bars_long = _long_bars(aligned)
    features = _features_from_bars(aligned)
    append_bars(run_dir, bars_long, run_id=effective_run_id)
    append_features(run_dir, features, run_id=effective_run_id)

    idx = next(iter(aligned.values())).index
    if len(idx) < 10:
        raise RuntimeError("Insufficient bars for Phase 1 backtest loop")
    split_at = max(5, int(len(idx) * 0.5))
    train_index = pd.DatetimeIndex(idx[:split_at])
    test_index = pd.DatetimeIndex(idx[split_at:])
    if len(test_index) < 2:
        raise RuntimeError("Insufficient test bars after train/test split")

    train_start = pd.Timestamp(train_index.min())
    train_end = pd.Timestamp(train_index.max())
    train_data = {sym: df[(df.index >= train_start) & (df.index <= train_end)] for sym, df in aligned.items()}

    pairs_engine = PairsEngine(cfg.pairs)
    pairs_engine.fit(train_data)
    trend_engine = TrendEngine(cfg.trend)
    _train_trend_safely(cfg, trend_engine, train_data)
    orchestrator = RegimeOrchestrator(cfg.regime, cfg.risk)
    hmm = _fit_hmm_from_training(cfg, train_data)
    if hmm is not None:
        orchestrator._hmm = hmm  # noqa: SLF001

    result = run_local_backtest(
        cfg=cfg,
        aligned_data=aligned,
        test_index=test_index,
        pairs_engine=pairs_engine,
        trend_engine=trend_engine,
        orchestrator=orchestrator,
        costs=cfg.execution_costs,
        mode="hybrid",
    )

    signals = result.signals.copy()
    fills = result.fills.copy()
    targets = fills.loc[:, ["timestamp", "symbol", "target_weight"]].copy() if not fills.empty else pd.DataFrame(columns=["timestamp", "symbol", "target_weight"])
    orders = (
        fills.loc[:, ["timestamp", "symbol"]].assign(order_type="market")
        if not fills.empty
        else pd.DataFrame(columns=["timestamp", "symbol", "order_type"])
    )

    append_signals(run_dir, signals, run_id=effective_run_id)
    append_targets(run_dir, targets, run_id=effective_run_id)
    append_orders(run_dir, orders, run_id=effective_run_id)
    append_fills(run_dir, fills, run_id=effective_run_id)
    append_equity_curve(run_dir, result.equity_curve.loc[:, ["timestamp", "equity"]], run_id=effective_run_id)
    append_reconciliation_events(run_dir, [], run_id=effective_run_id)
    append_risk_events(
        run_dir,
        pd.DataFrame(
            [
                {"timestamp": now.isoformat(), "reason": "phase1_start", "run_id": effective_run_id},
                {"timestamp": datetime.now(UTC).isoformat(), "reason": "phase1_complete", "run_id": effective_run_id},
            ]
        ),
        run_id=effective_run_id,
    )
    append_broker_events(
        run_dir,
        [
            {
                "timestamp": now.isoformat(),
                "event": "phase1_start",
                "run_id": effective_run_id,
                "symbols": symbols,
                "bar_frequency": cfg.data.bar_frequency,
            },
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "phase1_complete",
                "run_id": effective_run_id,
            },
        ],
        run_id=effective_run_id,
    )

    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(result.metrics, indent=2), encoding="utf-8")
    bar_health.to_csv(run_dir / "bar_health.csv", index=False)
    return run_dir
