"""Walk-forward runner and artifact generation for Phase 5 proof bundles."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import yaml

from fx_hybrid_engine.contracts import SCHEMA_VERSION
from fx_hybrid_engine.data.alignment import align_multi
from fx_hybrid_engine.data.provider import fetch_multi_symbol
from fx_hybrid_engine.engines.pair_validity import PairValidityManager
from fx_hybrid_engine.engines.pairs import PairsEngine
from fx_hybrid_engine.engines.pairs_scan import build_pairs_diagnostics, scan_candidate_pairs
from fx_hybrid_engine.engines.trend_features import compute_trend_features, feature_columns
from fx_hybrid_engine.engines.trend import TrendEngine
from fx_hybrid_engine.engines.types import Direction, EngineType, Signal
from fx_hybrid_engine.evaluation.attribution import (
    evaluate_proof_checks,
    pnl_attribution_engine,
    pnl_attribution_engine_x_regime,
    pnl_attribution_regime,
)
from fx_hybrid_engine.evaluation.local_backtester import (
    LocalBacktestResult,
    PrecomputedStep,
    run_local_backtest,
)
from fx_hybrid_engine.evaluation.regime_compare import (
    run_regime_comparison_for_split,
    write_regime_comparison_report,
)
from fx_hybrid_engine.evaluation.robustness import (
    robustness_diagnostics,
    run_cost_sweep,
    run_parameter_sweep,
)
from fx_hybrid_engine.features.indicators import momentum_slope, rolling_vol
from fx_hybrid_engine.features.spread import compute_spread, zscore
from fx_hybrid_engine.regime.hmm import RegimeHMM
from fx_hybrid_engine.regime.orchestrator import RegimeOrchestrator
from fx_hybrid_engine.reporting.regime_qa import regime_events, summarize_regime_qa
from fx_hybrid_engine.utils.config import EngineConfig, load_config
from fx_hybrid_engine.utils.identity import hash_config, make_run_id, resolve_git_commit

logger = logging.getLogger("fxhe.evaluation.walkforward")

Mode = Literal["hybrid", "pairs_only", "trend_only"]
ALL_MODES: tuple[Mode, ...] = ("hybrid", "pairs_only", "trend_only")
PIPELINE_VERSION = "phase5.1"


def _utc(ts: object) -> pd.Timestamp:
    out = pd.Timestamp(ts)
    if out.tzinfo is None:
        return out.tz_localize("UTC")
    return out.tz_convert("UTC")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_df(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


def _write_json(payload: dict[str, object], path: Path) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _fingerprint_payload(
    cfg: EngineConfig,
    *,
    max_splits: int | None,
    modes: tuple[Mode, ...],
) -> dict[str, object]:
    all_symbols = sorted(list({s for pair in cfg.pair_list for s in pair} | set(cfg.trend_symbols)))
    return {
        "symbols": all_symbols,
        "pair_list": [list(pair) for pair in cfg.pair_list],
        "trend_symbols": list(cfg.trend_symbols),
        "bar_frequency": cfg.data.bar_frequency,
        "data_profile": cfg.walkforward.data_profile,
        "date_range": {
            "start_date": cfg.walkforward.start_date,
            "end_date": cfg.walkforward.end_date,
        },
        "split_windows": {
            "train_window_days": cfg.walkforward.train_window_days,
            "test_window_days": cfg.walkforward.test_window_days,
            "step_days": cfg.walkforward.step_days,
            "max_splits": max_splits,
        },
        "trend_params": asdict(cfg.trend),
        "pairs_params": asdict(cfg.pairs),
        "regime_params": asdict(cfg.regime),
        "mode_list": list(modes),
        "cost_params": asdict(cfg.execution_costs),
        "seed": cfg.robustness.random_seed,
    }


def _cache_fingerprint(payload: dict[str, object]) -> str:
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _build_local_smoke_data(
    symbols: list[str],
    start: str,
    end: str,
    seed: int = 1234,
) -> dict[str, pd.DataFrame]:
    """Build deterministic synthetic OHLC data with mixed trend/chop dynamics."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start=start, end=end, freq="B", tz="UTC")
    n = len(idx)
    if n < 300:
        idx = pd.date_range(end=pd.Timestamp(end), periods=300, freq="B", tz="UTC")
        n = len(idx)

    common = np.cumsum(rng.normal(0.0, 0.004, n))
    trend_seg = np.concatenate(
        [
            np.linspace(0.0, 0.08, n // 3),
            np.zeros(n // 3),
            np.linspace(0.0, -0.06, n - 2 * (n // 3)),
        ]
    )
    data: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols):
        beta = 0.7 + (i % 4) * 0.15
        idio = np.cumsum(rng.normal(0.0, 0.0015 + 0.0003 * (i % 3), n))
        seasonal = 0.01 * np.sin(np.linspace(0, 16, n) + i)
        log_price = 5.0 + beta * common + idio + trend_seg + seasonal
        close = np.exp(log_price)
        open_px = close * (1.0 + rng.normal(0.0, 0.0008, n))
        high = np.maximum(open_px, close) * (1.0 + abs(rng.normal(0.0009, 0.0003, n)))
        low = np.minimum(open_px, close) * (1.0 - abs(rng.normal(0.0009, 0.0003, n)))
        df = pd.DataFrame(
            {
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.nan,
            },
            index=idx,
        )
        data[sym] = df
    return data


def load_walkforward_data(cfg: EngineConfig) -> dict[str, pd.DataFrame]:
    all_symbols = sorted(list({s for pair in cfg.pair_list for s in pair} | set(cfg.trend_symbols)))
    if cfg.walkforward.data_profile == "openbb":
        raw = fetch_multi_symbol(
            all_symbols,
            start=cfg.walkforward.start_date,
            end=cfg.walkforward.end_date,
            provider=cfg.data.openbb_provider,
            frequency=cfg.data.bar_frequency,
            source=cfg.data.source,
            seed=cfg.robustness.random_seed,
        )
        return align_multi(raw)
    return _build_local_smoke_data(
        all_symbols,
        start=cfg.walkforward.start_date,
        end=cfg.walkforward.end_date,
        seed=cfg.robustness.random_seed,
    )


def generate_walkforward_splits(
    index: pd.DatetimeIndex,
    train_window_days: int,
    test_window_days: int,
    step_days: int,
    max_splits: int | None = None,
) -> list[dict[str, object]]:
    """Generate rolling train/test splits from a UTC timestamp index."""
    if len(index) == 0:
        return []
    idx = pd.DatetimeIndex(sorted(pd.to_datetime(index, utc=True).unique()))
    first = idx.min()
    last = idx.max()
    train_delta = pd.Timedelta(days=int(train_window_days))
    test_delta = pd.Timedelta(days=int(test_window_days))
    step_delta = pd.Timedelta(days=int(step_days))

    splits: list[dict[str, object]] = []
    cursor = first
    split_idx = 0
    while True:
        train_start = cursor
        train_end = train_start + train_delta
        test_start = train_end
        test_end = test_start + test_delta
        if test_end > last:
            break

        train_idx = idx[(idx >= train_start) & (idx < train_end)]
        test_idx = idx[(idx >= test_start) & (idx < test_end)]
        if len(train_idx) > 5 and len(test_idx) > 2:
            splits.append(
                {
                    "split_idx": split_idx,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "n_train_bars": int(len(train_idx)),
                    "n_test_bars": int(len(test_idx)),
                    "train_index": train_idx,
                    "test_index": test_idx,
                }
            )
            split_idx += 1
            if max_splits is not None and len(splits) >= int(max_splits):
                break
        cursor = cursor + step_delta
        if cursor >= last:
            break
    return splits


def _slice_data(
    aligned_data: dict[str, pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for sym, df in aligned_data.items():
        sliced = df[(df.index >= start) & (df.index < end)]
        if not sliced.empty:
            out[sym] = sliced
    return out


def _run_pairs_scan_and_state(
    cfg: EngineConfig,
    split_eval_data: dict[str, pd.DataFrame],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, dict[str, object]],
    dict[str, pd.Series],
    dict[str, str],
    pd.DataFrame,
]:
    """Run rolling pair scans and derive tradability state timelines."""
    scan_result = scan_candidate_pairs(
        split_eval_data,
        cfg.pair_list,
        cointegration_threshold=cfg.pairs.cointegration_pvalue_threshold,
        spread_window=cfg.pairs.spread_window,
        entry_zscore=cfg.pairs.entry_zscore,
        min_train_bars=cfg.pairs_policy.min_train_bars,
        scan_frequency_bars=cfg.pairs_policy.scan_frequency_bars,
    )
    pair_ids = scan_result.candidates["pair_id"].tolist() if not scan_result.candidates.empty else []
    manager = PairValidityManager(
        p_enter=cfg.pairs_policy.p_enter,
        p_exit=cfg.pairs_policy.p_exit,
        p_break=cfg.pairs_policy.p_break,
        p_recover=cfg.pairs_policy.p_recover,
        break_scans_required=cfg.pairs_policy.break_scans_required,
        spread_std_spike_k=cfg.pairs_policy.spread_std_spike_k,
        beta_jump_abs=cfg.pairs_policy.beta_jump_abs,
        cooldown_scans=cfg.pairs_policy.cooldown_scans,
        entry_zscore=cfg.pairs.entry_zscore,
    )
    manager.register_pairs(pair_ids)

    timeline_rows: list[dict[str, object]] = []
    if cfg.pairs_policy.scan_enabled and not scan_result.scans.empty:
        for _, grp in scan_result.scans.groupby("scan_idx", sort=True):
            manager.apply_scan(grp)
            ts_raw = grp["timestamp"].dropna()
            if ts_raw.empty:
                continue
            ts = pd.to_datetime(ts_raw.iloc[-1], utc=True, errors="coerce")
            if pd.isna(ts):
                continue
            for pair_id, state in manager.state_map().items():
                timeline_rows.append({"timestamp": ts, "pair_id": pair_id, "state": state})

    timeline_df = pd.DataFrame(timeline_rows, columns=["timestamp", "pair_id", "state"])
    timeline_map: dict[str, pd.Series] = {}
    if not timeline_df.empty:
        for pair_id, grp in timeline_df.groupby("pair_id", sort=True):
            series = pd.Series(grp["state"].values, index=pd.to_datetime(grp["timestamp"], utc=True))
            timeline_map[str(pair_id)] = series.sort_index()

    state_map = manager.state_map()
    diagnostics = build_pairs_diagnostics(
        scan_result.scans,
        pair_ids=pair_ids,
        cointegration_threshold=cfg.pairs.cointegration_pvalue_threshold,
        entry_zscore=cfg.pairs.entry_zscore,
        state_map=state_map,
        trade_counts={},
    )
    return (
        scan_result.candidates,
        scan_result.scans,
        manager.events_df(),
        manager.snapshot_payload(),
        timeline_map,
        state_map,
        diagnostics,
    )


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


def _train_trend_engine_safely(
    cfg: EngineConfig,
    trend_engine: TrendEngine,
    train_data: dict[str, pd.DataFrame],
    split_idx: int,
    context: str,
) -> None:
    requested_version = str(cfg.trend.model_version or "").strip()
    if requested_version:
        try:
            trend_engine.load_model_version(cfg.trend.model_root, requested_version)
            return
        except FileNotFoundError:
            logger.warning(
                "Trend model version '%s' unavailable for %s split %s; falling back to in-split training.",
                requested_version,
                context,
                split_idx,
            )
        except ValueError as exc:
            logger.warning(
                "Trend model version '%s' rejected for %s split %s (%s); falling back to in-split training.",
                requested_version,
                context,
                split_idx,
                exc,
            )
    required = cfg.trend.sma_slow + cfg.trend.feature_lookback + 10
    eligible = {
        sym: df
        for sym, df in train_data.items()
        if "close" in df.columns and len(df) >= required
    }
    if not eligible:
        logger.warning(
            "Trend training skipped for %s split %s: insufficient bars (need >= %s). Using fallback.",
            context,
            split_idx,
            required,
        )
        return
    try:
        trend_engine.train(eligible)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Trend training failed for %s split %s; fallback enabled (%s)",
            context,
            split_idx,
            exc,
        )


def _build_precomputed_steps(
    cfg: EngineConfig,
    eval_data: dict[str, pd.DataFrame],
    test_index: pd.DatetimeIndex,
    pairs_engine: PairsEngine,
    trend_engine: TrendEngine,
    orchestrator: RegimeOrchestrator,
) -> list[PrecomputedStep]:
    test_index = pd.DatetimeIndex(sorted(pd.to_datetime(test_index, utc=True).unique()))
    if len(test_index) == 0:
        return []

    # Current prices map: timestamp -> {symbol: close}
    prices_by_ts: dict[pd.Timestamp, dict[str, float]] = {}
    for ts in test_index:
        prices: dict[str, float] = {}
        for sym, df in eval_data.items():
            if ts in df.index:
                prices[sym] = float(df.at[ts, "close"])
        prices_by_ts[ts] = prices

    # Pairs signal cache
    pair_signals_map: dict[pd.Timestamp, list[Signal]] = {ts: [] for ts in test_index}
    for (sym_a, sym_b), beta in pairs_engine._betas.items():  # noqa: SLF001
        if sym_a not in eval_data or sym_b not in eval_data:
            continue
        spread = compute_spread(eval_data[sym_a]["close"], eval_data[sym_b]["close"], beta)
        zs = zscore(spread, cfg.pairs.spread_window).reindex(test_index)
        pair_id = f"{sym_a}-{sym_b}"
        for ts, current_z in zs.items():
            if pd.isna(current_z):
                continue
            pair_state = pairs_engine._state_for(pair_id, ts)  # noqa: SLF001
            size = cfg.pairs.max_position_pct
            confidence = abs(float(current_z)) / cfg.pairs.entry_zscore
            if current_z < -cfg.pairs.entry_zscore and pair_state == "TRADABLE":
                pair_signals_map[ts].append(
                    Signal(
                        sym_a,
                        Direction.LONG,
                        size,
                        EngineType.PAIRS,
                        ts,
                        confidence=confidence,
                        metadata={"pair_id": pair_id, "pair_state": pair_state},
                    )
                )
                pair_signals_map[ts].append(
                    Signal(
                        sym_b,
                        Direction.SHORT,
                        size * beta,
                        EngineType.PAIRS,
                        ts,
                        confidence=confidence,
                        metadata={"pair_id": pair_id, "pair_state": pair_state},
                    )
                )
            elif current_z > cfg.pairs.entry_zscore and pair_state == "TRADABLE":
                pair_signals_map[ts].append(
                    Signal(
                        sym_a,
                        Direction.SHORT,
                        size,
                        EngineType.PAIRS,
                        ts,
                        confidence=confidence,
                        metadata={"pair_id": pair_id, "pair_state": pair_state},
                    )
                )
                pair_signals_map[ts].append(
                    Signal(
                        sym_b,
                        Direction.LONG,
                        size * beta,
                        EngineType.PAIRS,
                        ts,
                        confidence=confidence,
                        metadata={"pair_id": pair_id, "pair_state": pair_state},
                    )
                )
            elif abs(float(current_z)) < cfg.pairs.exit_zscore:
                pair_signals_map[ts].append(
                    Signal(sym_a, Direction.FLAT, 0.0, EngineType.PAIRS, ts, metadata={"pair_id": pair_id, "pair_state": pair_state})
                )
                pair_signals_map[ts].append(
                    Signal(sym_b, Direction.FLAT, 0.0, EngineType.PAIRS, ts, metadata={"pair_id": pair_id, "pair_state": pair_state})
                )

    # Trend signal cache
    trend_signals_map: dict[pd.Timestamp, list[Signal]] = {ts: [] for ts in test_index}
    feat_cols = feature_columns(cfg.trend)
    for sym in cfg.trend_symbols:
        if sym not in eval_data:
            continue
        feats = compute_trend_features(eval_data[sym]["close"], cfg.trend).reindex(test_index)
        if trend_engine._model is not None:  # noqa: SLF001
            valid_mask = feats[feat_cols].notna().all(axis=1)
            probs_by_ts: dict[pd.Timestamp, tuple[float, float]] = {}
            if valid_mask.any():
                valid_rows = feats.loc[valid_mask, feat_cols]
                probs = trend_engine._model.predict_proba(valid_rows.values)  # noqa: SLF001
                for ts, (p_down, p_up) in zip(valid_rows.index, probs, strict=True):
                    probs_by_ts[ts] = (float(p_down), float(p_up))
            for ts in test_index:
                proba = probs_by_ts.get(ts)
                if proba is None:
                    trend_signals_map[ts].append(Signal(sym, Direction.FLAT, 0.0, EngineType.TREND, ts))
                    continue
                p_down, p_up = proba
                meta = {
                    "p_up": float(p_up),
                    "p_down": float(p_down),
                    "decision_threshold": float(trend_engine.decision_threshold),
                    "model_version": trend_engine.model_version or "unknown",
                }
                if p_up >= trend_engine.decision_threshold:
                    trend_signals_map[ts].append(Signal(sym, Direction.LONG, 1.0, EngineType.TREND, ts, confidence=p_up, metadata=meta))
                elif p_down >= trend_engine.decision_threshold:
                    trend_signals_map[ts].append(Signal(sym, Direction.SHORT, 1.0, EngineType.TREND, ts, confidence=p_down, metadata=meta))
                else:
                    trend_signals_map[ts].append(Signal(sym, Direction.FLAT, 0.0, EngineType.TREND, ts, confidence=max(p_up, p_down), metadata=meta))
        else:
            for ts, row in feats.iterrows():
                sig = trend_engine.generate_from_features_row(sym, row, ts)
                trend_signals_map[ts].append(sig)

    # Regime cache
    regime_labels: dict[pd.Timestamp, str] = {}
    regime_probs: dict[pd.Timestamp, dict[str, float]] = {}
    if not orchestrator._hmm.is_fitted:  # noqa: SLF001
        for ts in test_index:
            regime_labels[ts] = "CHOP"
            regime_probs[ts] = {"TREND": 0.0, "CHOP": 1.0, "RISK_OFF": 0.0}
    else:
        vol_map: dict[str, pd.Series] = {}
        mom_map: dict[str, pd.Series] = {}
        for sym, df in eval_data.items():
            if "close" not in df.columns or len(df) < cfg.regime.vol_window + 2:
                continue
            vol_map[sym] = rolling_vol(df["close"], window=cfg.regime.vol_window, annualize=True)
            mom_map[sym] = momentum_slope(df["close"], window=cfg.regime.vol_window)

        if not vol_map:
            for ts in test_index:
                regime_labels[ts] = orchestrator.current_state
                regime_probs[ts] = orchestrator.state_probabilities or {"TREND": 0.0, "CHOP": 1.0, "RISK_OFF": 0.0}
        else:
            vol_df = pd.concat(vol_map, axis=1)
            mom_df = pd.concat(mom_map, axis=1)
            obs_df = pd.DataFrame(
                {
                    "vol": vol_df.mean(axis=1, skipna=True),
                    "mom": mom_df.mean(axis=1, skipna=True),
                }
            ).dropna()
            if obs_df.empty:
                for ts in test_index:
                    regime_labels[ts] = orchestrator.current_state
                    regime_probs[ts] = orchestrator.state_probabilities or {"TREND": 0.0, "CHOP": 1.0, "RISK_OFF": 0.0}
            else:
                obs_idx = obs_df.index.view("int64")
                obs_values = obs_df[["vol", "mom"]].values
                prev_label = orchestrator.current_state
                prev_prob = orchestrator.state_probabilities or {"TREND": 0.0, "CHOP": 1.0, "RISK_OFF": 0.0}
                for ts in test_index:
                    pos = int(np.searchsorted(obs_idx, ts.value, side="right") - 1)
                    if pos < 1:
                        regime_labels[ts] = prev_label
                        regime_probs[ts] = prev_prob
                        continue
                    start = max(0, pos - cfg.regime.obs_window + 1)
                    window = obs_values[start : pos + 1]
                    label = orchestrator.update_regime_from_observations(window)
                    prob = orchestrator.state_probabilities or prev_prob
                    regime_labels[ts] = label
                    regime_probs[ts] = prob
                    prev_label = label
                    prev_prob = prob

    steps: list[PrecomputedStep] = []
    for ts in test_index:
        steps.append(
            PrecomputedStep(
                timestamp=ts,
                prices=prices_by_ts.get(ts, {}),
                regime_label=regime_labels.get(ts, "CHOP"),
                probabilities=regime_probs.get(ts, {"TREND": 0.0, "CHOP": 1.0, "RISK_OFF": 0.0}),
                pairs_signals=pair_signals_map.get(ts, []),
                trend_signals=trend_signals_map.get(ts, []),
            )
        )
    return steps


def _save_split_mode_artifacts(
    mode_dir: Path,
    cfg: EngineConfig,
    split_info: dict[str, object],
    mode: Mode,
    result: LocalBacktestResult,
    runtime_metadata: dict[str, object],
) -> None:
    _ensure_dir(mode_dir)
    _write_df(result.signals, mode_dir / "signals.csv")
    _write_df(result.trades, mode_dir / "trades.csv")
    _write_df(result.fills, mode_dir / "fills.csv")
    _write_df(result.equity_curve, mode_dir / "equity_curve.csv")
    _write_df(result.regime_posteriors, mode_dir / "regime_posteriors.csv")
    _write_df(result.engine_allocations, mode_dir / "engine_allocations.csv")

    metrics = dict(result.metrics)
    metrics.update(
        {
            "mode": mode,
            "split_idx": int(split_info["split_idx"]),
            "train_start": _utc(split_info["train_start"]).isoformat(),
            "train_end": _utc(split_info["train_end"]).isoformat(),
            "test_start": _utc(split_info["test_start"]).isoformat(),
            "test_end": _utc(split_info["test_end"]).isoformat(),
            **runtime_metadata,
        }
    )
    with open(mode_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    snapshot = {
        "mode": mode,
        "split_idx": int(split_info["split_idx"]),
        "runtime": runtime_metadata,
        "config": asdict(cfg),
    }
    with open(mode_dir / "config_snapshot.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(snapshot, f, sort_keys=False)


def _evaluate_hybrid_metrics_for_cfg(
    cfg: EngineConfig,
    aligned_data: dict[str, pd.DataFrame],
    splits: list[dict[str, object]],
    precompute: bool = True,
) -> dict[str, float]:
    records: list[dict[str, float]] = []
    for split in splits:
        train_start = _utc(split["train_start"])
        test_end = _utc(split["test_end"])
        train_end = _utc(split["train_end"])
        train_data = _slice_data(aligned_data, train_start, train_end)
        if not train_data:
            continue

        pairs = PairsEngine(cfg.pairs)
        pairs.fit(train_data)

        trend = TrendEngine(cfg.trend)
        _train_trend_engine_safely(
            cfg,
            trend,
            train_data,
            int(split["split_idx"]),
            context="param_sweep",
        )

        hmm = _fit_hmm_from_training(cfg, train_data)
        orch = RegimeOrchestrator(cfg.regime, cfg.risk)
        if hmm is not None:
            orch._hmm = hmm  # noqa: SLF001

        eval_data = _slice_data(aligned_data, train_start, test_end)
        (
            _candidates_df,
            _scan_df,
            _state_events_df,
            _snapshot,
            state_timeline,
            state_map,
            _diag_df,
        ) = _run_pairs_scan_and_state(cfg, eval_data)
        pairs.set_pair_states(state_map)
        pairs.set_pair_state_timeline(state_timeline)
        pre_steps = None
        if precompute:
            pre_steps = _build_precomputed_steps(
                cfg=cfg,
                eval_data=eval_data,
                test_index=pd.DatetimeIndex(split["test_index"]),
                pairs_engine=pairs,
                trend_engine=trend,
                orchestrator=orch,
            )
            orch = RegimeOrchestrator(cfg.regime, cfg.risk)
            if hmm is not None:
                orch._hmm = hmm  # noqa: SLF001
        result = run_local_backtest(
            cfg=cfg,
            aligned_data=eval_data,
            test_index=pd.DatetimeIndex(split["test_index"]),
            pairs_engine=pairs,
            trend_engine=trend,
            orchestrator=orch,
            costs=cfg.execution_costs,
            mode="hybrid",
            precomputed_steps=pre_steps,
        )
        records.append(result.metrics)

    df = pd.DataFrame(records)
    if df.empty:
        return {"median_total_return": 0.0, "median_sharpe": 0.0, "worst_max_drawdown": 0.0}
    return {
        "median_total_return": float(df["total_return"].median()),
        "median_sharpe": float(df["sharpe"].median()),
        "worst_max_drawdown": float(df["max_drawdown"].max()),
    }


def run_walkforward(
    config_path: str | Path = "config/default.yaml",
    wf_run_id: str | None = None,
    max_splits: int | None = None,
    run_report: bool = False,
    skip_robustness: bool = False,
    precompute: bool = True,
    mode_reuse: bool = True,
    run_regime_compare: bool | None = None,
) -> Path:
    """Run Phase 5 walk-forward pipeline and return the run directory."""
    cfg = load_config(config_path)
    config_payload = asdict(cfg)
    config_hash = hash_config(config_payload)
    now = datetime.now(UTC)
    run_id = wf_run_id or make_run_id(now, config_hash)
    run_root = Path(cfg.walkforward.output_root) / run_id
    _ensure_dir(run_root)
    effective_max_splits = max_splits if max_splits is not None else cfg.walkforward.max_splits
    fingerprint_payload = _fingerprint_payload(
        cfg,
        max_splits=effective_max_splits,
        modes=ALL_MODES,
    )
    cache_fingerprint = _cache_fingerprint(fingerprint_payload)
    runtime_metadata: dict[str, object] = {
        "precompute_enabled": bool(precompute),
        "mode_reuse_enabled": bool(mode_reuse),
        "cache_fingerprint": cache_fingerprint,
        "pipeline_version": PIPELINE_VERSION,
        "config_hash": config_hash,
        "schema_version": SCHEMA_VERSION,
        "seed": int(cfg.robustness.random_seed),
        "regime_compare_enabled": bool(cfg.regime_compare.enabled if run_regime_compare is None else run_regime_compare),
    }

    logger.info("Loading data profile '%s'...", cfg.walkforward.data_profile)
    aligned = load_walkforward_data(cfg)
    if not aligned:
        raise RuntimeError("No aligned data available for walk-forward evaluation")
    common_index = next(iter(aligned.values())).index

    split_specs = generate_walkforward_splits(
        common_index,
        train_window_days=cfg.walkforward.train_window_days,
        test_window_days=cfg.walkforward.test_window_days,
        step_days=cfg.walkforward.step_days,
        max_splits=effective_max_splits,
    )
    if not split_specs:
        raise RuntimeError("No walk-forward splits generated; widen date range or adjust window sizes")
    compare_enabled = cfg.regime_compare.enabled if run_regime_compare is None else bool(run_regime_compare)
    all_symbols = sorted(list({s for pair in cfg.pair_list for s in pair} | set(cfg.trend_symbols)))
    run_manifest = {
        "wf_run_id": run_id,
        "created_at_utc": now.isoformat(),
        "config_path": str(Path(config_path).resolve()),
        "git_commit": resolve_git_commit(),
        "config_hash": config_hash,
        "schema_version": SCHEMA_VERSION,
        "seed": int(cfg.robustness.random_seed),
        "precompute_enabled": bool(precompute),
        "mode_reuse_enabled": bool(mode_reuse),
        "skip_robustness": bool(skip_robustness),
        "regime_compare_enabled": compare_enabled,
        "data_profile": cfg.walkforward.data_profile,
        "symbols": all_symbols,
        "pair_list": [list(pair) for pair in cfg.pair_list],
        "trend_symbols": list(cfg.trend_symbols),
        "split_params": {
            "train_window_days": cfg.walkforward.train_window_days,
            "test_window_days": cfg.walkforward.test_window_days,
            "step_days": cfg.walkforward.step_days,
            "max_splits": effective_max_splits,
            "generated_splits": len(split_specs),
        },
        "cost_params": asdict(cfg.execution_costs),
        "cache_fingerprint": cache_fingerprint,
        "pipeline_version": PIPELINE_VERSION,
        "trend_model_requested": str(cfg.trend.model_version),
        "trend_feature_schema_hash": TrendEngine(cfg.trend).feature_schema_hash,
    }
    with open(run_root / "run_manifest.json", "w", encoding="utf-8") as f:
        json.dump(run_manifest, f, indent=2)

    split_rows = []
    all_metric_rows: list[dict[str, object]] = []
    all_trade_rows: list[pd.DataFrame] = []
    hybrid_equity_by_split: dict[int, pd.DataFrame] = {}
    all_pair_diagnostics_rows: list[pd.DataFrame] = []
    regime_qa_rows: list[dict[str, object]] = []
    regime_compare_rows: list[pd.DataFrame] = []

    for split in split_specs:
        split_idx = int(split["split_idx"])
        split_rows.append(
            {
                "split_idx": split_idx,
                "train_start": _utc(split["train_start"]).isoformat(),
                "train_end": _utc(split["train_end"]).isoformat(),
                "test_start": _utc(split["test_start"]).isoformat(),
                "test_end": _utc(split["test_end"]).isoformat(),
                "n_train_bars": int(split["n_train_bars"]),
                "n_test_bars": int(split["n_test_bars"]),
            }
        )

        split_dir = run_root / f"split_{split_idx:03d}"
        _ensure_dir(split_dir)

        train_start = _utc(split["train_start"])
        train_end = _utc(split["train_end"])
        test_end = _utc(split["test_end"])
        train_data = _slice_data(aligned, train_start, train_end)
        eval_data = _slice_data(aligned, train_start, test_end)
        if not train_data or not eval_data:
            logger.warning("Skipping split %s due to empty train/eval data", split_idx)
            continue

        (
            pairs_candidates_df,
            pairs_scan_df,
            pair_state_events_df,
            pair_state_snapshot,
            pair_state_timeline,
            pair_state_map,
            split_pairs_diag_df,
        ) = _run_pairs_scan_and_state(cfg, eval_data)
        _write_df(pairs_candidates_df, split_dir / "pairs_candidates.csv")
        _write_df(pairs_scan_df, split_dir / "pairs_scan.csv")
        _write_df(pair_state_events_df, split_dir / "pair_state_events.csv")
        _write_json(pair_state_snapshot, split_dir / "pair_state_snapshot.json")
        _write_df(split_pairs_diag_df, split_dir / "pairs_diagnostics.csv")

        pairs_engine = PairsEngine(cfg.pairs)
        pairs_engine.fit(train_data)
        pairs_engine.set_pair_states(pair_state_map)
        pairs_engine.set_pair_state_timeline(pair_state_timeline)
        trend_engine = TrendEngine(cfg.trend)
        _train_trend_engine_safely(
            cfg,
            trend_engine,
            train_data,
            split_idx,
            context="walkforward",
        )
        split_runtime_metadata = {
            **runtime_metadata,
            "trend_model_version": trend_engine.model_version or "in_memory_or_fallback",
            "trend_feature_schema_hash": trend_engine.feature_schema_hash,
        }
        hmm = _fit_hmm_from_training(cfg, train_data)

        pre_steps_shared: list[PrecomputedStep] | None = None
        if precompute and mode_reuse:
            pre_orch = RegimeOrchestrator(cfg.regime, cfg.risk)
            if hmm is not None:
                pre_orch._hmm = hmm  # noqa: SLF001
            pre_steps_shared = _build_precomputed_steps(
                cfg=cfg,
                eval_data=eval_data,
                test_index=pd.DatetimeIndex(split["test_index"]),
                pairs_engine=pairs_engine,
                trend_engine=trend_engine,
                orchestrator=pre_orch,
            )

        for mode in ALL_MODES:
            orch = RegimeOrchestrator(cfg.regime, cfg.risk)
            if hmm is not None:
                orch._hmm = hmm  # noqa: SLF001
            pre_steps = pre_steps_shared
            if precompute and not mode_reuse:
                pre_steps = _build_precomputed_steps(
                    cfg=cfg,
                    eval_data=eval_data,
                    test_index=pd.DatetimeIndex(split["test_index"]),
                    pairs_engine=pairs_engine,
                    trend_engine=trend_engine,
                    orchestrator=orch,
                )
                orch = RegimeOrchestrator(cfg.regime, cfg.risk)
                if hmm is not None:
                    orch._hmm = hmm  # noqa: SLF001

            result = run_local_backtest(
                cfg=cfg,
                aligned_data=eval_data,
                test_index=pd.DatetimeIndex(split["test_index"]),
                pairs_engine=pairs_engine,
                trend_engine=trend_engine,
                orchestrator=orch,
                costs=cfg.execution_costs,
                mode=mode,
                precomputed_steps=pre_steps,
            )
            mode_dir = split_dir / mode
            _save_split_mode_artifacts(mode_dir, cfg, split, mode, result, split_runtime_metadata)
            row = {
                "split_idx": split_idx,
                "mode": mode,
                **split_runtime_metadata,
                **result.metrics,
            }
            all_metric_rows.append(row)
            if not result.trades.empty:
                trades = result.trades.copy()
                trades["split_idx"] = split_idx
                all_trade_rows.append(trades)
            if mode == "hybrid":
                hybrid_equity_by_split[split_idx] = result.equity_curve.copy()
                trade_counts = (
                    result.trades.loc[result.trades["pair_id"].notna(), "pair_id"].value_counts().to_dict()
                    if not result.trades.empty and "pair_id" in result.trades.columns
                    else {}
                )
                split_pairs_diag_df = build_pairs_diagnostics(
                    pairs_scan_df,
                    pair_ids=pairs_candidates_df["pair_id"].tolist() if not pairs_candidates_df.empty else [],
                    cointegration_threshold=cfg.pairs.cointegration_pvalue_threshold,
                    entry_zscore=cfg.pairs.entry_zscore,
                    state_map=pair_state_map,
                    trade_counts={str(k): int(v) for k, v in trade_counts.items()},
                )
                _write_df(split_pairs_diag_df, split_dir / "pairs_diagnostics.csv")
                if not split_pairs_diag_df.empty:
                    diag_with_split = split_pairs_diag_df.copy()
                    diag_with_split["split_idx"] = split_idx
                    all_pair_diagnostics_rows.append(diag_with_split)

                if cfg.regime_qa.enabled:
                    reg_df = result.regime_posteriors.copy()
                    reg_events = regime_events(reg_df)
                    _write_df(reg_events, split_dir / "regime_events.csv")
                    hmm_state_map = hmm.state_map if hmm is not None else {}
                    hmm_state_meta = hmm.state_metadata if hmm is not None else {"state_map": {}, "state_order": [], "means": []}
                    qa_summary = summarize_regime_qa(reg_df, cfg=cfg.regime_qa, hmm_state_map=hmm_state_map)
                    _write_json(qa_summary, split_dir / "regime_summary.json")
                    _write_json(hmm_state_meta, split_dir / "hmm_state_map.json")
                    occ = qa_summary.get("occupancy", {})
                    checks = qa_summary.get("checks", {})
                    regime_qa_rows.append(
                        {
                            "split_idx": split_idx,
                            "n_bars": int(qa_summary.get("n_bars", 0)),
                            "n_transitions": int(qa_summary.get("n_transitions", 0)),
                            "transitions_per_1000_bars": float(qa_summary.get("transitions_per_1000_bars", 0.0)),
                            "max_posterior_sum_error": float(qa_summary.get("max_posterior_sum_error", 1.0)),
                            "occupancy_trend": float(occ.get("TREND", 0.0)),
                            "occupancy_chop": float(occ.get("CHOP", 0.0)),
                            "occupancy_risk_off": float(occ.get("RISK_OFF", 0.0)),
                            "posterior_sum_ok": bool(checks.get("posterior_sum_ok", False)),
                            "churn_ok": bool(checks.get("churn_ok", False)),
                            "occupancy_ok": bool(checks.get("occupancy_ok", False)),
                            "regime_qa_pass": bool(qa_summary.get("pass", False)),
                        }
                    )

        if compare_enabled:
            comp_df = run_regime_comparison_for_split(
                cfg=cfg,
                eval_data=eval_data,
                test_index=pd.DatetimeIndex(split["test_index"]),
                pairs_engine=pairs_engine,
                trend_engine=trend_engine,
                hmm_model=hmm,
                split_idx=split_idx,
            )
            if not comp_df.empty:
                regime_compare_rows.append(comp_df)

    splits_df = pd.DataFrame(split_rows)
    _write_df(splits_df, run_root / "splits.csv")

    metrics_df = pd.DataFrame(all_metric_rows)
    _write_df(metrics_df, run_root / "metrics_by_split.csv")

    pairs_diag_df = pd.concat(all_pair_diagnostics_rows, ignore_index=True) if all_pair_diagnostics_rows else pd.DataFrame()
    _write_df(pairs_diag_df, run_root / "pairs_diagnostics_by_split.csv")

    regime_qa_df = pd.DataFrame(regime_qa_rows)
    _write_df(regime_qa_df, run_root / "regime_qa_by_split.csv")

    all_trades_df = pd.concat(all_trade_rows, ignore_index=True) if all_trade_rows else pd.DataFrame()
    hybrid_trades = all_trades_df.loc[all_trades_df["mode"] == "hybrid"].copy() if not all_trades_df.empty else pd.DataFrame()

    by_engine = pnl_attribution_engine(hybrid_trades)
    by_regime = pnl_attribution_regime(hybrid_trades)
    by_engine_regime = pnl_attribution_engine_x_regime(hybrid_trades)
    _write_df(by_engine, run_root / "pnl_attribution_engine.csv")
    _write_df(by_regime, run_root / "pnl_attribution_regime.csv")
    _write_df(by_engine_regime, run_root / "pnl_attribution_engine_x_regime.csv")

    proof = evaluate_proof_checks(hybrid_trades, cfg.proof_gates) if not hybrid_trades.empty else {"pass": False, "checks": {}, "reason": "no hybrid trades"}
    with open(run_root / "proof_checks.json", "w", encoding="utf-8") as f:
        json.dump(proof, f, indent=2)

    cost_sweep_df = run_cost_sweep(hybrid_equity_by_split, cfg.execution_costs, cfg.robustness)
    _write_df(cost_sweep_df, run_root / "robustness_cost_sweep.csv")

    if not skip_robustness:
        param_sweep_df = run_parameter_sweep(
            cfg,
            evaluate_fn=lambda c: _evaluate_hybrid_metrics_for_cfg(c, aligned, split_specs, precompute=precompute),
        )
    else:
        param_sweep_df = pd.DataFrame(
            columns=[
                "sample_idx",
                "entry_zscore",
                "exit_zscore",
                "cointegration_pvalue_threshold",
                "trend_signal_threshold",
                "max_leverage",
                "drawdown_kill_pct",
                "median_total_return",
                "median_sharpe",
                "worst_max_drawdown",
            ]
        )
    _write_df(param_sweep_df, run_root / "robustness_param_sweep.csv")

    base_hybrid = metrics_df.loc[metrics_df["mode"] == "hybrid"] if not metrics_df.empty else pd.DataFrame()
    base_median_return = float(base_hybrid["total_return"].median()) if not base_hybrid.empty else 0.0
    robust_diag = robustness_diagnostics(param_sweep_df, base_median_return)
    with open(run_root / "robustness_diagnostics.json", "w", encoding="utf-8") as f:
        json.dump(robust_diag, f, indent=2)

    if compare_enabled:
        compare_df = pd.concat(regime_compare_rows, ignore_index=True) if regime_compare_rows else pd.DataFrame()
        _write_df(compare_df, run_root / "regime_comparison_metrics.csv")
        write_regime_comparison_report(compare_df, run_root)

    # Optional Lean parity placeholder. Failures here should not fail local evidence bundle.
    if cfg.walkforward.backend in ("lean", "both"):
        parity_rows = []
        for split in split_specs:
            for mode in ALL_MODES:
                parity_rows.append(
                    {
                        "split_idx": int(split["split_idx"]),
                        "mode": mode,
                        "status": "not_run",
                        "note": "Lean parity is optional and not required for local proof bundle",
                    }
                )
        _write_df(pd.DataFrame(parity_rows), run_root / "lean_parity_summary.csv")

    if run_report or cfg.walkforward.auto_report:
        from fx_hybrid_engine.reporting.phase5_report import generate_phase5_report

        generate_phase5_report(run_root)

    return run_root
