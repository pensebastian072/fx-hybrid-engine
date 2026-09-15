"""Broker-agnostic local paper session and shared strategy-cycle helpers."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from fx_hybrid_engine.brokers.tastytrade import (
    TastytradeApiClient,
    TastytradeApiError,
    TastytradeCredentials,
)
from fx_hybrid_engine.contracts import SCHEMA_VERSION
from fx_hybrid_engine.data.alignment import normalize_universe
from fx_hybrid_engine.data.provider import fetch_multi_symbol
from fx_hybrid_engine.engines.pair_validity import PairValidityManager
from fx_hybrid_engine.engines.pairs import PairsEngine
from fx_hybrid_engine.engines.pairs_scan import build_pairs_diagnostics, scan_candidate_pairs
from fx_hybrid_engine.engines.trend import TrendEngine
from fx_hybrid_engine.engines.trend_features import compute_trend_features, feature_columns
from fx_hybrid_engine.evaluation.local_backtester import LocalBacktestResult, run_local_backtest
from fx_hybrid_engine.evaluation.phase1_runner import (
    _features_from_bars,
    _fit_hmm_from_training,
    _long_bars,
    _train_trend_safely,
)
from fx_hybrid_engine.features.advanced import compute_all_advanced
from fx_hybrid_engine.features.spread import compute_spread, hedge_ratio, zscore
from fx_hybrid_engine.lean.runtime_safety import evaluate_runtime_safety
from fx_hybrid_engine.ops.circuit_breakers import BreakerContext
from fx_hybrid_engine.ops.health import HealthPolicy
from fx_hybrid_engine.ops.ladder import normalize_stage, resolve_ladder_caps
from fx_hybrid_engine.ops.layout import build_run_dir
from fx_hybrid_engine.ops.ops_summary import generate_ops_summary
from fx_hybrid_engine.ops.storage import (
    append_bars,
    append_broker_context,
    append_broker_events,
    append_equity_curve,
    append_features,
    append_fills,
    append_indicator_snapshots,
    append_orders,
    append_pair_scans,
    append_pair_state_events,
    append_reconciliation_events,
    append_risk_events,
    append_signals,
    append_targets,
    initialize_run_metadata,
)
from fx_hybrid_engine.regime.orchestrator import RegimeOrchestrator
from fx_hybrid_engine.utils.config import EngineConfig
from fx_hybrid_engine.utils.identity import hash_config, make_run_id, resolve_git_commit


def all_symbols(cfg: EngineConfig) -> list[str]:
    return sorted(set(cfg.pair_observe_symbols) | set(cfg.trend_symbols))


def observe_pair_list(cfg: EngineConfig) -> list[list[str]]:
    return cfg.pair_observe_list


def preview_symbol_map(cfg: EngineConfig, symbols: list[str]) -> dict[str, str]:
    raw_map = cfg.tastytrade.symbol_map or {}
    return {
        symbol: str(raw_map.get(symbol, "")).strip()
        for symbol in symbols
        if str(raw_map.get(symbol, "")).strip()
    }


def empty_stream_frames(run_id: str) -> dict[str, pd.DataFrame]:
    ts = datetime.now(UTC).isoformat()
    return {
        "bars": pd.DataFrame(
            columns=["timestamp", "run_id", "symbol", "open", "high", "low", "close"]
        ),
        "features": pd.DataFrame(columns=["timestamp", "run_id", "symbol"]),
        "signals": pd.DataFrame(columns=["timestamp", "run_id", "symbol", "engine_source"]),
        "targets": pd.DataFrame(columns=["timestamp", "run_id", "symbol", "target_weight"]),
        "orders": pd.DataFrame(columns=["timestamp", "run_id", "symbol", "order_type"]),
        "fills": pd.DataFrame(columns=["timestamp", "run_id", "symbol", "fill_price"]),
        "equity_curve": pd.DataFrame(columns=["timestamp", "run_id", "equity"]),
        "risk_events": pd.DataFrame(
            [{"timestamp": ts, "run_id": run_id, "reason": "session_initialized"}]
        ),
    }


def write_empty_streams(run_dir: Path, frames: dict[str, pd.DataFrame], *, run_id: str) -> None:
    append_bars(run_dir, frames["bars"], run_id=run_id)
    append_features(run_dir, frames["features"], run_id=run_id)
    append_signals(run_dir, frames["signals"], run_id=run_id)
    append_targets(run_dir, frames["targets"], run_id=run_id)
    append_orders(run_dir, frames["orders"], run_id=run_id)
    append_fills(run_dir, frames["fills"], run_id=run_id)
    append_equity_curve(run_dir, frames["equity_curve"], run_id=run_id)
    append_risk_events(run_dir, frames["risk_events"], run_id=run_id)
    append_reconciliation_events(run_dir, [], run_id=run_id)


def write_session_state(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _recent_window(cfg: EngineConfig, *, now: datetime) -> tuple[str, str]:
    lookback_days = max(1, int(cfg.trend.train_window_days) + int(cfg.trend.test_window_days))
    end = now.date()
    start = end - timedelta(days=lookback_days)
    return start.isoformat(), end.isoformat()


def _split_train_test_index(
    index: pd.DatetimeIndex,
    *,
    test_window_days: int,
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    sorted_index = pd.DatetimeIndex(sorted(pd.to_datetime(index, utc=True).unique()))
    if len(sorted_index) < 10:
        raise ValueError("Paper strategy cycle requires at least 10 aligned bars")

    cutoff = sorted_index.max() - pd.Timedelta(days=max(1, int(test_window_days)))
    test_index = sorted_index[sorted_index >= cutoff]
    if len(test_index) < 2:
        fallback_size = max(2, min(len(sorted_index) // 5, len(sorted_index) - 1))
        test_index = sorted_index[-fallback_size:]
    train_index = sorted_index[sorted_index < test_index.min()]
    if len(train_index) < 5:
        raise ValueError(
            "Paper strategy cycle does not have enough training bars before the execution window"
        )
    return train_index, test_index


def _orders_from_fills(
    fills: pd.DataFrame,
    *,
    symbol_map: dict[str, str],
) -> pd.DataFrame:
    columns = [
        "timestamp",
        "symbol",
        "order_type",
        "broker_symbol",
        "target_weight",
        "delta_weight",
        "engine_source",
        "regime_label",
        "mode",
    ]
    if fills.empty:
        return pd.DataFrame(columns=columns)
    orders = fills.loc[
        :,
        [
            "timestamp",
            "symbol",
            "target_weight",
            "delta_weight",
            "engine_source",
            "regime_label",
            "mode",
        ],
    ].copy()
    orders["broker_symbol"] = orders["symbol"].map(symbol_map).fillna("")
    orders["order_type"] = orders["delta_weight"].apply(
        lambda value: "paper_buy" if float(value) > 0 else "paper_sell"
    )
    return orders.loc[:, columns]


def _fills_for_storage(
    fills: pd.DataFrame,
    *,
    symbol_map: dict[str, str],
) -> pd.DataFrame:
    columns = [
        "timestamp",
        "symbol",
        "broker_symbol",
        "fill_price",
        "target_weight",
        "delta_weight",
        "engine_source",
        "regime_label",
        "commission_bps",
        "slippage_bps",
        "mode",
    ]
    if fills.empty:
        return pd.DataFrame(columns=columns)
    stored = fills.copy()
    stored["broker_symbol"] = stored["symbol"].map(symbol_map).fillna("")
    stored = stored.rename(columns={"price": "fill_price"})
    return stored.loc[:, columns]


def _ui_trades(trades: pd.DataFrame) -> list[dict[str, object]]:
    if trades.empty:
        return []
    rows: list[dict[str, object]] = []
    for idx, row in trades.iterrows():
        entry_price = float(row.get("entry_price", 0.0) or 0.0)
        exit_raw = row.get("exit_price")
        exit_price = None if pd.isna(exit_raw) else float(exit_raw)
        entry_weight = float(row.get("entry_weight", 0.0) or 0.0)
        side = "long" if entry_weight >= 0 else "short"
        direction = 1.0 if entry_weight >= 0 else -1.0
        pnl_pct = 0.0
        if entry_price and exit_price is not None:
            pnl_pct = (((exit_price / entry_price) - 1.0) * direction) * 100.0
        if side == "long":
            stop = entry_price * 0.995 if entry_price else 0.0
            take_profit = entry_price * 1.01 if entry_price else 0.0
        else:
            stop = entry_price * 1.005 if entry_price else 0.0
            take_profit = entry_price * 0.99 if entry_price else 0.0
        engine_source = str(row.get("engine_source", "trend") or "trend")
        rows.append(
            {
                "id": f"paper_{idx + 1:04d}",
                "time": str(row.get("entry_timestamp", "")),
                "exit_time": None
                if pd.isna(row.get("exit_timestamp"))
                else str(row.get("exit_timestamp")),
                "symbol": str(row.get("symbol", "")),
                "engine_source": engine_source,
                "side": side,
                "entry": entry_price,
                "exit": exit_price,
                "stop": stop,
                "take_profit": take_profit,
                "size": abs(entry_weight),
                "pnl": float(row.get("pnl", 0.0) or 0.0),
                "pnl_pct": pnl_pct,
                "close_reason": None
                if pd.isna(row.get("close_reason"))
                else str(row.get("close_reason")),
                "regime_at_entry": str(row.get("entry_regime", "TREND") or "TREND"),
                "tags": [engine_source],
            }
        )
    return rows


def _update_run_manifest(run_dir: Path, updates: dict[str, Any]) -> None:
    path = run_dir / "run_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    _write_json(path, payload)


def _tastytrade_credentials_available(cfg: EngineConfig) -> bool:
    required = (
        cfg.tastytrade.client_id_env,
        cfg.tastytrade.client_secret_env,
        cfg.tastytrade.refresh_token_env,
    )
    return all(str(os.getenv(name, "")).strip() for name in required)


def _build_tastytrade_client(cfg: EngineConfig) -> TastytradeApiClient:
    creds = TastytradeCredentials(
        client_id=os.environ[cfg.tastytrade.client_id_env],
        client_secret=os.environ[cfg.tastytrade.client_secret_env],
        refresh_token=os.environ[cfg.tastytrade.refresh_token_env],
    )
    return TastytradeApiClient(
        credentials=creds,
        oauth_token_url=cfg.tastytrade.oauth_token_url,
        accounts_url=cfg.tastytrade.accounts_url,
        balances_url_template=cfg.tastytrade.balances_url_template,
    )


def _resolve_tastytrade_account_number(
    cfg: EngineConfig,
    accounts: list[dict[str, object]],
) -> str | None:
    selected = str(os.getenv(cfg.tastytrade.account_number_env, "")).strip()
    available = [
        str(account.get("account_number", "")).strip()
        for account in accounts
        if str(account.get("account_number", "")).strip()
    ]
    if selected:
        return selected if selected in available else None
    if len(available) == 1:
        return available[0]
    return None


def _collect_broker_context(
    *,
    cfg: EngineConfig,
    symbol_map: dict[str, str],
    symbols: list[str],
) -> tuple[dict[str, object], list[dict[str, object]], Any | None, str | None]:
    missing_symbols = sorted(symbol for symbol in symbols if not symbol_map.get(symbol))
    base_context = {
        "provider": "tastytrade",
        "available": False,
        "connection_status": "broker_context_unavailable",
        "account_number": None,
        "symbol_map_ready_count": int(len(symbol_map)),
        "symbol_map_missing": missing_symbols,
        "positions_count": 0,
        "open_orders_count": 0,
        "accounts_count": 0,
        "balances": None,
        "positions": [],
        "open_orders": [],
        "error": None,
    }

    if not _tastytrade_credentials_available(cfg):
        event = {
            **base_context,
            "event": "broker_context_unavailable",
            "reason": "missing_credentials",
        }
        return (
            {**base_context, "error": "Missing tastytrade credentials in environment."},
            [event],
            None,
            None,
        )

    client = _build_tastytrade_client(cfg)
    try:
        accounts = client.list_accounts()
        account_payload = [
            {
                "account_number": account.account_number,
                "account_type": account.account_type,
                "authority_level": account.authority_level,
            }
            for account in accounts
        ]
        account_number = _resolve_tastytrade_account_number(
            cfg,
            accounts=[dict(item) for item in account_payload],
        )
        if account_number is None:
            error_message = (
                "Unable to resolve tastytrade account number from available accounts. "
                f"Set {cfg.tastytrade.account_number_env} to choose one."
            )
            event = {
                **base_context,
                "accounts_count": len(account_payload),
                "accounts": account_payload,
                "event": "broker_context_unavailable",
                "reason": "account_number_unresolved",
            }
            return (
                {**base_context, "accounts_count": len(account_payload), "accounts": account_payload, "error": error_message},
                [event],
                None,
                None,
            )

        balances = client.get_balances(account_number)
        positions = client.list_positions(account_number)
        live_orders = client.list_live_orders(account_number)
        context = {
            **base_context,
            "available": True,
            "connection_status": "connected",
            "account_number": account_number,
            "accounts_count": len(account_payload),
            "accounts": account_payload,
            "balances": balances.raw,
            "positions_count": len(positions),
            "positions": [
                {
                    "symbol": position.symbol,
                    "quantity": float(position.quantity),
                }
                for position in positions
            ],
            "open_orders_count": len(live_orders),
            "open_orders": live_orders,
        }
        event = {
            **context,
            "event": "broker_context_snapshot",
        }
        return context, [event], client, account_number
    except (KeyError, TastytradeApiError, ValueError) as exc:
        event = {
            **base_context,
            "event": "broker_context_unavailable",
            "reason": "api_error",
            "error": str(exc),
        }
        return ({**base_context, "error": str(exc)}, [event], None, None)


def _position_sign(value: float, *, eps: float = 1e-9) -> int:
    if value > eps:
        return 1
    if value < -eps:
        return -1
    return 0


def _latest_target_weights(fills: pd.DataFrame, symbols: list[str]) -> dict[str, float]:
    targets = {symbol: 0.0 for symbol in symbols}
    if fills.empty:
        return targets
    ordered = fills.sort_values(["timestamp", "symbol"])
    for symbol, group in ordered.groupby("symbol", sort=False):
        if symbol in targets:
            targets[symbol] = float(group["target_weight"].iloc[-1])
    return targets


def _paper_position_plan(
    *,
    fills: pd.DataFrame,
    symbols: list[str],
    symbol_map: dict[str, str],
) -> list[dict[str, object]]:
    targets = _latest_target_weights(fills, symbols)
    plan: list[dict[str, object]] = []
    for symbol in symbols:
        target_weight = float(targets.get(symbol, 0.0))
        broker_symbol = symbol_map.get(symbol, "")
        direction = _position_sign(target_weight)
        plan.append(
            {
                "symbol": symbol,
                "broker_symbol": broker_symbol,
                "target_weight": target_weight,
                "direction": ("long" if direction > 0 else "short" if direction < 0 else "flat"),
                "orderable_contract_ready": str(broker_symbol).startswith("/"),
            }
        )
    return plan


def _paper_rollout_profile(
    *,
    cfg: EngineConfig,
    symbol_map: dict[str, str],
) -> dict[str, object]:
    stage = normalize_stage(cfg.micro_live_ladder.active_stage)
    caps = resolve_ladder_caps(stage=stage)
    return {
        "active_strategy_stack": ["pairs", "trend", "regime_hmm"],
        "deferred_ml4t_components": [
            "ml_signal_engine",
            "volatility_regime_classifier",
            "broker_submitted_tastytrade_orders",
        ],
        "cointegration_method": cfg.pairs.cointegration_method,
        "trend_decision_threshold": float(
            cfg.trend.decision_threshold or cfg.trend.signal_threshold
        ),
        "pairs_entry_zscore": float(cfg.pairs.entry_zscore),
        "pairs_exit_zscore": float(cfg.pairs.exit_zscore),
        "risk": {
            "max_leverage": float(cfg.risk.max_leverage),
            "stop_loss_pct": float(cfg.risk.stop_loss_pct),
            "drawdown_kill_pct": float(cfg.risk.drawdown_kill_pct),
            "vol_target_annual": float(cfg.risk.vol_target_annual),
            "risk_off_size_multiplier": float(cfg.risk.risk_off_size_multiplier),
            "ladder_stage": stage,
            "ladder_caps": asdict(caps),
        },
        "data": {
            "source": cfg.data.source,
            "bar_frequency": cfg.data.bar_frequency,
        },
        "pair_trade_universe": cfg.pair_list,
        "pair_observe_universe": cfg.pair_observe_symbols,
        "broker_symbol_map": symbol_map,
    }


def _health_policy(cfg: EngineConfig) -> HealthPolicy:
    thresholds = cfg.health_monitor.state_machine_thresholds or {}
    return HealthPolicy(
        data_stale_seconds=int(thresholds.get("data_stale_seconds", 300)),
        degraded_rejects=int(thresholds.get("degraded_rejects", 3)),
        broker_down_rejects=int(thresholds.get("broker_down_rejects", 8)),
    )


def _paper_safety_summary(
    *,
    cfg: EngineConfig,
    run_id: str,
    bars: pd.DataFrame,
    fills: pd.DataFrame,
    bar_health: pd.DataFrame,
    client: Any | None,
    account_number: str | None,
    symbol_map: dict[str, str],
    symbols: list[str],
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    latest_bar_timestamp = None if bars.empty else str(bars["timestamp"].iloc[-1])
    missing_bars = (
        int(bar_health["gap_count"].sum())
        if not bar_health.empty and "gap_count" in bar_health.columns
        else 0
    )
    expected_signs = {
        symbol: _position_sign(weight)
        for symbol, weight in _latest_target_weights(fills, symbols).items()
        if _position_sign(weight) != 0
    }

    actual_signs: dict[str, float] = {}
    actual_order_ids: set[str] = set()
    broker_positions_available = False
    broker_orders_available = False
    if client is not None and account_number:
        if hasattr(client, "list_positions"):
            broker_positions = client.list_positions(account_number)
            reverse_map = {mapped: symbol for symbol, mapped in symbol_map.items()}
            for position in broker_positions:
                mapped_symbol = reverse_map.get(position.symbol)
                if mapped_symbol:
                    actual_signs[mapped_symbol] = float(_position_sign(position.quantity))
            broker_positions_available = True
        if hasattr(client, "list_live_orders"):
            live_orders = client.list_live_orders(account_number)
            actual_order_ids = {
                str(order_id)
                for order in live_orders
                for order_id in [order.get("id")]
                if order_id is not None and str(order_id).strip()
            }
            broker_orders_available = True

    reconciliation_cfg = (
        cfg.reconciliation if (broker_positions_available or broker_orders_available) else None
    )
    reconciliation_mode = "broker_validated" if reconciliation_cfg is not None else "skipped"
    reconciliation_status = "evaluated" if reconciliation_cfg is not None else "skipped"
    reconciliation_reason = None if reconciliation_cfg is not None else "broker_state_unavailable_or_local_only"
    mismatch_cycles = 1 if reconciliation_cfg and expected_signs != actual_signs else 0
    snapshot = evaluate_runtime_safety(
        run_id=run_id,
        last_bar_timestamp_utc=latest_bar_timestamp,
        consecutive_rejects=0,
        missing_bars=missing_bars,
        broker_connected=True,
        health_policy=_health_policy(cfg),
        breaker_ctx=BreakerContext(
            daily_return=0.0,
            weekly_return=0.0,
            consecutive_losses=0,
            realized_vol_multiple=1.0,
            reject_count=0,
        ),
        circuit_breakers_cfg=cfg.circuit_breakers,
        reconciliation_cfg=reconciliation_cfg,
        expected_holdings=expected_signs,
        actual_holdings=actual_signs,
        expected_order_ids=set(),
        actual_order_ids=actual_order_ids,
        mismatch_cycles=mismatch_cycles,
    )
    reconciliation_events: list[dict[str, object]] = []
    if snapshot.reconciliation is not None:
        reconciliation_events.append(
            {
                "event": "paper_reconciliation_snapshot",
                "reconciliation_mode": reconciliation_mode,
                "reconciliation_status": reconciliation_status,
                "reconciliation_reason": reconciliation_reason,
                "resolved": not snapshot.reconciliation.pause_entries,
                "health_state": snapshot.health_state,
                "close_only": snapshot.close_only,
                "expected_holdings": expected_signs,
                "actual_holdings": actual_signs,
                "actual_open_order_ids": sorted(actual_order_ids),
                "holdings_match": snapshot.reconciliation.holdings_match,
                "orders_match": snapshot.reconciliation.orders_match,
                "pause_entries": snapshot.reconciliation.pause_entries,
                "flatten_required": snapshot.reconciliation.flatten_required,
                "missing_symbols": snapshot.reconciliation.missing_symbols,
                "extra_symbols": snapshot.reconciliation.extra_symbols,
                "quantity_mismatches": snapshot.reconciliation.quantity_mismatches,
            }
        )
    else:
        reconciliation_events.append(
            {
                "event": "paper_reconciliation_skipped",
                "reconciliation_mode": reconciliation_mode,
                "reconciliation_status": reconciliation_status,
                "reconciliation_reason": reconciliation_reason,
                "resolved": True,
                "reason": "broker_state_unavailable_or_local_only",
                "expected_holdings": expected_signs,
            }
        )

    summary = {
        "health_state": snapshot.health_state,
        "close_only": snapshot.close_only,
        "health_reasons": snapshot.health_reasons,
        "breaker_result": snapshot.breaker_result,
        "expected_holdings_sign": expected_signs,
        "actual_holdings_sign": actual_signs,
        "broker_positions_available": broker_positions_available,
        "broker_orders_available": broker_orders_available,
        "reconciliation_enabled": snapshot.reconciliation is not None,
        "reconciliation_mode": reconciliation_mode,
        "reconciliation_status": reconciliation_status,
        "reconciliation_reason": reconciliation_reason,
        "missing_bars_count": missing_bars,
        "latest_bar_timestamp": latest_bar_timestamp,
    }
    if snapshot.reconciliation is not None:
        summary["reconciliation"] = asdict(snapshot.reconciliation)
    return summary, snapshot.risk_events, reconciliation_events


def _run_pairs_scan_with_state(
    cfg: EngineConfig,
    data: dict[str, pd.DataFrame],
    *,
    pair_list: list[list[str]],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str], dict[str, pd.Series]]:
    scan_result = scan_candidate_pairs(
        data,
        pair_list,
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
            timeline_map[str(pair_id)] = pd.Series(
                grp["state"].values,
                index=pd.to_datetime(grp["timestamp"], utc=True),
            ).sort_index()

    return scan_result.scans, manager.events_df(), manager.state_map(), timeline_map


def _state_for_timestamp(
    pair_id: str,
    timestamp: object,
    *,
    state_map: dict[str, str],
    timeline_map: dict[str, pd.Series],
) -> str:
    timeline = timeline_map.get(pair_id)
    if timeline is not None and len(timeline) > 0:
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        eligible = timeline.loc[timeline.index <= ts]
        if not eligible.empty:
            return str(eligible.iloc[-1])
    return str(state_map.get(pair_id, "WATCH"))


def _trade_counts_by_pair(trades: pd.DataFrame) -> dict[str, int]:
    if trades.empty or "pair_id" not in trades.columns:
        return {}
    counts: dict[str, int] = {}
    for pair_id, group in trades.dropna(subset=["pair_id"]).groupby("pair_id", sort=False):
        counts[str(pair_id)] = int(len(group))
    return counts


def _pair_zscore_series(
    cfg: EngineConfig,
    execution_data: dict[str, pd.DataFrame],
    *,
    pair_list: list[list[str]],
    scans_df: pd.DataFrame,
) -> dict[str, list[dict[str, object]]]:
    payload: dict[str, list[dict[str, object]]] = {}
    latest_betas: dict[str, float] = {}
    if not scans_df.empty:
        valid = scans_df.loc[scans_df["reason"] == "ok"].sort_values("timestamp")
        for pair_id, group in valid.groupby("pair_id", sort=False):
            beta = group["beta"].iloc[-1]
            if pd.notna(beta):
                latest_betas[str(pair_id)] = float(beta)

    for sym_a, sym_b in pair_list:
        pair_id = f"{sym_a}-{sym_b}"
        if sym_a not in execution_data or sym_b not in execution_data:
            payload[pair_id] = []
            continue
        close_a = execution_data[sym_a]["close"]
        close_b = execution_data[sym_b]["close"]
        common = close_a.index.intersection(close_b.index)
        if common.empty:
            payload[pair_id] = []
            continue
        hist_a = close_a.reindex(common)
        hist_b = close_b.reindex(common)
        beta = latest_betas.get(pair_id)
        if beta is None:
            try:
                beta = float(hedge_ratio(hist_a, hist_b))
            except Exception:  # noqa: BLE001
                payload[pair_id] = []
                continue
        spread = compute_spread(hist_a, hist_b, beta)
        scores = zscore(spread, cfg.pairs.spread_window).dropna()
        payload[pair_id] = [
            {"date": pd.Timestamp(ts).isoformat(), "zscore": float(value)}
            for ts, value in scores.items()
        ]
    return payload


def _build_pairs_ui_artifacts(
    *,
    cfg: EngineConfig,
    aligned: dict[str, pd.DataFrame],
    execution_data: dict[str, pd.DataFrame],
    result: LocalBacktestResult,
) -> tuple[
    list[dict[str, object]],
    dict[str, dict[str, object]],
    pd.DataFrame,
    pd.DataFrame,
]:
    observed_pairs = observe_pair_list(cfg)
    trade_pair_ids = {f"{sym_a}-{sym_b}" for sym_a, sym_b in cfg.pair_list}
    scans_df, events_df, state_map, timeline_map = _run_pairs_scan_with_state(
        cfg,
        aligned,
        pair_list=observed_pairs,
    )
    pair_ids = [f"{sym_a}-{sym_b}" for sym_a, sym_b in observed_pairs]
    trade_counts = _trade_counts_by_pair(result.trades)
    diagnostics_df = build_pairs_diagnostics(
        scans_df,
        pair_ids=pair_ids,
        cointegration_threshold=cfg.pairs.cointegration_pvalue_threshold,
        entry_zscore=cfg.pairs.entry_zscore,
        state_map=state_map,
        trade_counts=trade_counts,
    )
    diagnostics = []
    for row in diagnostics_df.to_dict(orient="records"):
        row["in_trade_universe"] = row["pair_id"] in trade_pair_ids
        diagnostics.append(row)
    zscore_payload = _pair_zscore_series(
        cfg,
        execution_data,
        pair_list=observed_pairs,
        scans_df=scans_df,
    )

    pair_history: dict[str, dict[str, object]] = {}
    for pair_id in pair_ids:
        scans = scans_df.loc[scans_df["pair_id"] == pair_id].sort_values("timestamp")
        scan_history = [
            {
                "date": pd.Timestamp(row["timestamp"]).isoformat()
                if pd.notna(row["timestamp"])
                else "",
                "pvalue": None if pd.isna(row["pvalue"]) else float(row["pvalue"]),
                "beta": None if pd.isna(row["beta"]) else float(row["beta"]),
                "spread_std": None
                if pd.isna(row["spread_std"])
                else float(row["spread_std"]),
                "z_abs_p95": None
                if pd.isna(row["z_abs_p95"])
                else float(row["z_abs_p95"]),
                "state": _state_for_timestamp(
                    pair_id,
                    row["timestamp"],
                    state_map=state_map,
                    timeline_map=timeline_map,
                ),
            }
            for _, row in scans.iterrows()
        ]
        events = events_df.loc[events_df["pair_id"] == pair_id].sort_values("timestamp")
        state_events = [
            {
                "date": pd.Timestamp(row["timestamp"]).isoformat(),
                "event": f"{row['from_state']} -> {row['to_state']}",
                "reason": str(row["reason"]),
            }
            for _, row in events.iterrows()
        ]
        pair_history[pair_id] = {
            "in_trade_universe": pair_id in trade_pair_ids,
            "scan_history": scan_history,
            "zscore_series": zscore_payload.get(pair_id, []),
            "state_events": state_events,
        }
    return diagnostics, pair_history, scans_df, events_df


def _build_signals_sample(signals: pd.DataFrame, *, max_rows: int = 200) -> list[dict[str, object]]:
    if signals.empty:
        return []
    subset = signals.sort_values("timestamp").tail(max_rows)
    rows: list[dict[str, object]] = []
    for _, row in subset.iterrows():
        rows.append(
            {
                "timestamp": str(row.get("timestamp", "")),
                "symbol": str(row.get("symbol", "")),
                "direction": str(row.get("direction", "flat")),
                "size": float(row.get("size", 0.0) or 0.0),
                "engine_source": str(row.get("engine_source", "unknown")),
                "confidence": float(row.get("confidence", 0.0) or 0.0),
                "regime_label": str(row.get("regime_label", "TREND")),
                "trend_p_up": float(row.get("trend_p_up", 0.0) or 0.0),
                "trend_p_down": float(row.get("trend_p_down", 0.0) or 0.0),
                "decision_threshold": float(row.get("decision_threshold", 0.0) or 0.0),
                "trend_model_version": str(row.get("trend_model_version", "unknown") or "unknown"),
                "decision_reason": str(row.get("decision_reason", "") or ""),
            }
        )
    return rows


def _build_trend_model_meta(
    *,
    cfg: EngineConfig,
    trend_engine: TrendEngine,
    started_at: datetime,
) -> dict[str, object]:
    metadata = trend_engine.model_metadata
    created_at = str(metadata.get("created_at_utc", started_at.isoformat()))
    return {
        "model_version": str(metadata.get("model_version", trend_engine.model_version or "in_memory")),
        "training_window_days": int(metadata.get("train_window_days", cfg.trend.train_window_days)),
        "feature_schema_hash": str(
            metadata.get("feature_schema_hash", trend_engine.feature_schema_hash)
        ),
        "last_retrain_time": created_at,
        "calibration_score": metadata.get("calibration_score"),
        "feature_columns": list(metadata.get("feature_columns", feature_columns(cfg.trend))),
        "label_mode": str(metadata.get("label_mode", "binary")),
        "label_horizon_bars": int(
            metadata.get("label_horizon_bars", cfg.trend.label_horizon_bars)
        ),
        "label_threshold_bps": float(
            metadata.get("label_threshold_bps", cfg.trend.label_threshold_bps)
        ),
    }


def _build_indicator_snapshots(
    *,
    cfg: EngineConfig,
    execution_data: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for symbol, frame in execution_data.items():
        if "close" not in frame.columns:
            continue
        basic = compute_trend_features(frame["close"], cfg.trend)
        advanced = compute_all_advanced(
            frame["close"],
            high=frame["high"] if "high" in frame.columns else None,
            low=frame["low"] if "low" in frame.columns else None,
            volume=frame["volume"] if "volume" in frame.columns else None,
        )
        merged = pd.concat(
            [
                basic[
                    [
                        "close",
                        "sma_fast",
                        "sma_slow",
                        "rsi",
                        "realized_vol",
                        "momentum_slope",
                        "sma_crossover",
                    ]
                ],
                advanced[["macd_line", "macd_signal", "macd_histogram"]],
            ],
            axis=1,
        ).copy()
        price_delta = frame["close"].diff(3)
        macd_delta = merged["macd_histogram"].diff(3)
        merged["macd_bullish_divergence"] = (
            (price_delta < 0) & (macd_delta > 0)
        ).fillna(False)
        merged["macd_bearish_divergence"] = (
            (price_delta > 0) & (macd_delta < 0)
        ).fillna(False)
        merged = merged.reset_index().rename(columns={"index": "timestamp"})
        merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True, errors="coerce")
        merged["symbol"] = symbol
        rows.append(merged)

    if not rows:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "symbol",
                "close",
                "sma_fast",
                "sma_slow",
                "rsi",
                "realized_vol",
                "momentum_slope",
                "sma_crossover",
                "macd_line",
                "macd_signal",
                "macd_histogram",
                "macd_bullish_divergence",
                "macd_bearish_divergence",
            ]
        )
    return pd.concat(rows, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(
        drop=True
    )


def _decision_reason(row: pd.Series) -> str:
    direction = str(row.get("direction", "flat") or "flat")
    if direction == "long":
        return "threshold_long"
    if direction == "short":
        return "threshold_short"
    if pd.notna(row.get("trend_p_up")) or pd.notna(row.get("trend_p_down")):
        return "confidence_below_threshold"
    return "features_unavailable_or_fallback"


def _build_trend_decisions(
    *,
    signals: pd.DataFrame,
    indicator_snapshots: pd.DataFrame,
    max_rows: int = 200,
) -> list[dict[str, object]]:
    if signals.empty:
        return []
    trend_rows = signals.loc[signals["engine_source"] == "trend"].copy()
    if trend_rows.empty:
        return []

    if not indicator_snapshots.empty:
        join_cols = [
            "timestamp",
            "symbol",
            "rsi",
            "realized_vol",
            "sma_crossover",
            "macd_line",
            "macd_signal",
            "macd_histogram",
            "macd_bullish_divergence",
            "macd_bearish_divergence",
        ]
        snapshots = indicator_snapshots.loc[:, join_cols].copy()
        snapshots["timestamp"] = snapshots["timestamp"].astype(str)
        trend_rows = trend_rows.merge(
            snapshots,
            how="left",
            on=["timestamp", "symbol"],
        )

    trend_rows["decision_reason"] = trend_rows.apply(_decision_reason, axis=1)
    trend_rows = trend_rows.sort_values("timestamp").tail(max_rows)
    payload: list[dict[str, object]] = []
    for _, row in trend_rows.iterrows():
        divergence = "none"
        if bool(row.get("macd_bullish_divergence", False)):
            divergence = "bullish"
        elif bool(row.get("macd_bearish_divergence", False)):
            divergence = "bearish"
        payload.append(
            {
                "timestamp": str(row.get("timestamp", "")),
                "symbol": str(row.get("symbol", "")),
                "direction": str(row.get("direction", "flat")),
                "confidence": float(row.get("confidence", 0.0) or 0.0),
                "regime_label": str(row.get("regime_label", "TREND")),
                "trend_p_up": float(row.get("trend_p_up", 0.0) or 0.0),
                "trend_p_down": float(row.get("trend_p_down", 0.0) or 0.0),
                "decision_threshold": float(row.get("decision_threshold", 0.0) or 0.0),
                "decision_reason": str(row.get("decision_reason", "")),
                "trend_model_version": str(row.get("trend_model_version", "unknown") or "unknown"),
                "rsi": None if pd.isna(row.get("rsi")) else float(row.get("rsi")),
                "realized_vol": None
                if pd.isna(row.get("realized_vol"))
                else float(row.get("realized_vol")),
                "sma_crossover": None
                if pd.isna(row.get("sma_crossover"))
                else float(row.get("sma_crossover")),
                "macd_line": None
                if pd.isna(row.get("macd_line"))
                else float(row.get("macd_line")),
                "macd_signal": None
                if pd.isna(row.get("macd_signal"))
                else float(row.get("macd_signal")),
                "macd_histogram": None
                if pd.isna(row.get("macd_histogram"))
                else float(row.get("macd_histogram")),
                "observed_divergence": divergence,
            }
        )
    return payload


def _indicator_snapshot_payload(
    indicator_snapshots: pd.DataFrame,
    *,
    max_rows_per_symbol: int = 160,
) -> list[dict[str, object]]:
    if indicator_snapshots.empty:
        return []
    rows: list[dict[str, object]] = []
    for _, group in indicator_snapshots.groupby("symbol", sort=True):
        subset = group.sort_values("timestamp").tail(max_rows_per_symbol)
        for _, row in subset.iterrows():
            rows.append(
                {
                    "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                    "symbol": str(row.get("symbol", "")),
                    "close": float(row.get("close", 0.0) or 0.0),
                    "sma_fast": None if pd.isna(row.get("sma_fast")) else float(row.get("sma_fast")),
                    "sma_slow": None if pd.isna(row.get("sma_slow")) else float(row.get("sma_slow")),
                    "rsi": None if pd.isna(row.get("rsi")) else float(row.get("rsi")),
                    "realized_vol": None
                    if pd.isna(row.get("realized_vol"))
                    else float(row.get("realized_vol")),
                    "momentum_slope": None
                    if pd.isna(row.get("momentum_slope"))
                    else float(row.get("momentum_slope")),
                    "sma_crossover": None
                    if pd.isna(row.get("sma_crossover"))
                    else float(row.get("sma_crossover")),
                    "macd_line": None
                    if pd.isna(row.get("macd_line"))
                    else float(row.get("macd_line")),
                    "macd_signal": None
                    if pd.isna(row.get("macd_signal"))
                    else float(row.get("macd_signal")),
                    "macd_histogram": None
                    if pd.isna(row.get("macd_histogram"))
                    else float(row.get("macd_histogram")),
                    "macd_bullish_divergence": bool(
                        row.get("macd_bullish_divergence", False)
                    ),
                    "macd_bearish_divergence": bool(
                        row.get("macd_bearish_divergence", False)
                    ),
                }
            )
    return rows


def _bars_payload(bars: pd.DataFrame) -> list[dict[str, object]]:
    if bars.empty:
        return []
    ordered = bars.sort_values(["timestamp", "symbol"])
    rows: list[dict[str, object]] = []
    for _, row in ordered.iterrows():
        rows.append(
            {
                "time": pd.Timestamp(row["timestamp"]).isoformat().replace("+00:00", "Z"),
                "open": float(row.get("open", 0.0) or 0.0),
                "high": float(row.get("high", 0.0) or 0.0),
                "low": float(row.get("low", 0.0) or 0.0),
                "close": float(row.get("close", 0.0) or 0.0),
                "volume": float(row.get("volume", 0.0) or 0.0),
                "symbol": str(row.get("symbol", "")),
            }
        )
    return rows


def _equity_payload(equity_curve: pd.DataFrame) -> list[dict[str, object]]:
    if equity_curve.empty:
        return []
    ordered = equity_curve.sort_values("timestamp")
    return [
        {
            "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
            "equity": float(row.get("equity", 0.0) or 0.0),
            "regime_label": str(row.get("regime_label", "TREND") or "TREND"),
        }
        for _, row in ordered.iterrows()
    ]


def _ops_events_payload(
    *,
    regime_posteriors: pd.DataFrame,
    safety_summary: dict[str, object],
    broker_context: dict[str, object],
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    if not regime_posteriors.empty:
        ordered = regime_posteriors.sort_values("timestamp")
        previous = None
        for _, row in ordered.iterrows():
            current = str(row.get("regime_label", "TREND") or "TREND")
            if previous is not None and current != previous:
                events.append(
                    {
                        "timestamp": str(row.get("timestamp", "")),
                        "event_type": "regime_transition",
                        "message": f"Regime changed from {previous} to {current}.",
                        "symbols": [],
                    }
                )
            previous = current

    latest_bar_timestamp = str(safety_summary.get("latest_bar_timestamp", "") or "")
    if bool(safety_summary.get("close_only", False)):
        events.append(
            {
                "timestamp": latest_bar_timestamp,
                "event_type": "close_only_engage",
                "message": (
                    "Close-only is active due to "
                    + ", ".join(str(reason) for reason in safety_summary.get("health_reasons", []))
                ),
                "symbols": [],
            }
        )

    if broker_context.get("available"):
        events.append(
            {
                "timestamp": latest_bar_timestamp,
                "event_type": "deploy_change",
                "message": (
                    "Broker context connected: "
                    f"{broker_context.get('positions_count', 0)} positions, "
                    f"{broker_context.get('open_orders_count', 0)} open orders."
                ),
                "symbols": [],
            }
        )
    else:
        events.append(
            {
                "timestamp": latest_bar_timestamp,
                "event_type": "risk_event",
                "message": str(
                    broker_context.get("error")
                    or "Broker context unavailable for this local paper run."
                ),
                "symbols": [],
            }
        )

    return sorted(events, key=lambda row: str(row.get("timestamp", "")))


def _paper_metrics(result: LocalBacktestResult) -> dict[str, float]:
    return {
        "sharpe_ratio": float(result.metrics.get("sharpe", 0.0) or 0.0),
        "total_return": float(result.metrics.get("total_return", 0.0) or 0.0),
        "max_drawdown": float(result.metrics.get("max_drawdown", 0.0) or 0.0),
        "win_rate": float(result.metrics.get("win_rate", 0.0) or 0.0),
        "num_trades": int(result.metrics.get("trades", 0) or 0),
        "avg_trade_pnl": float(result.trades["pnl"].mean()) if not result.trades.empty else 0.0,
    }


def _no_trade_diagnostics(
    *,
    symbols: list[str],
    symbol_map: dict[str, str],
    pairs_diagnostics: list[dict[str, object]],
    signals: pd.DataFrame,
    result: LocalBacktestResult,
    safety_summary: dict[str, object],
    bar_health: pd.DataFrame,
) -> dict[str, object]:
    pair_reason_counts: dict[str, int] = {}
    tradable_pairs = 0
    for row in pairs_diagnostics:
        reason = str(row.get("primary_reason", "unknown") or "unknown")
        pair_reason_counts[reason] = pair_reason_counts.get(reason, 0) + 1
        if reason == "tradable":
            tradable_pairs += 1

    trend_rows = signals.loc[signals["engine_source"] == "trend"].copy() if not signals.empty else pd.DataFrame()
    confidence_misses = 0
    feature_unavailable = 0
    if not trend_rows.empty:
        for _, row in trend_rows.iterrows():
            if str(row.get("direction", "flat")) != "flat":
                continue
            if pd.notna(row.get("trend_p_up")) or pd.notna(row.get("trend_p_down")):
                confidence_misses += 1
            else:
                feature_unavailable += 1

    missing_bar_rows = (
        int(bar_health["gap_count"].sum())
        if not bar_health.empty and "gap_count" in bar_health.columns
        else 0
    )
    regime_distribution = (
        result.regime_posteriors["regime_label"].value_counts().to_dict()
        if not result.regime_posteriors.empty
        else {}
    )
    return {
        "signals_emitted": int(len(result.signals)),
        "fills_emitted": int(len(result.fills)),
        "closed_trades": int(len(result.trades)),
        "observed_pair_count": int(len(pairs_diagnostics)),
        "tradable_pair_count": int(tradable_pairs),
        "pair_reason_counts": pair_reason_counts,
        "trend_confidence_misses": int(confidence_misses),
        "trend_feature_unavailable": int(feature_unavailable),
        "close_only_active": bool(safety_summary.get("close_only", False)),
        "missing_bars_count": int(missing_bar_rows),
        "symbol_map_missing_count": int(len([symbol for symbol in symbols if not symbol_map.get(symbol)])),
        "regime_distribution": regime_distribution,
    }


def _paper_ops_payload(
    *,
    run_manifest: dict[str, object],
    session_state: dict[str, object],
    strategy_summary: dict[str, object],
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    broker_context: dict[str, object],
) -> dict[str, object]:
    last_bars = []
    if not bars.empty:
        recent = bars.sort_values("timestamp").tail(10)
        for _, row in recent.iterrows():
            last_bars.append(
                {
                    "timestamp": str(row.get("timestamp", "")),
                    "symbol": str(row.get("symbol", "")),
                    "close": float(row.get("close", 0.0) or 0.0),
                }
            )
    orders_per_hour = 0.0
    if not orders.empty and "timestamp" in orders.columns:
        parsed = pd.to_datetime(orders["timestamp"], utc=True, errors="coerce").dropna()
        if len(parsed) >= 2:
            elapsed_hours = max((parsed.max() - parsed.min()).total_seconds() / 3600.0, 1e-6)
            orders_per_hour = float(len(parsed) / elapsed_hours)
        elif len(parsed) == 1:
            orders_per_hour = 1.0

    safety_summary = strategy_summary.get("safety_summary", {})
    no_trade = strategy_summary.get("no_trade_diagnostics", {})
    return {
        "run_manifest": {
            "run_id": str(run_manifest.get("run_id", "")),
            "git_commit": str(run_manifest.get("git_commit", "unknown")),
            "config_hash": str(run_manifest.get("config_hash", "unknown")),
            "schema_version": str(run_manifest.get("schema_version", SCHEMA_VERSION)),
            "created_at_utc": str(
                run_manifest.get("startup_time_utc")
                or session_state.get("started_at_utc")
                or datetime.now(UTC).isoformat()
            ),
            "seed": int(run_manifest.get("seed", 0) or 0),
            "precompute_enabled": False,
            "mode_reuse_enabled": False,
            "data_profile": str(run_manifest.get("data_source", "paper")),
            "pipeline_version": str(strategy_summary.get("status", "paper")),
            "live_broker": run_manifest.get("live_broker"),
            "live_rail": run_manifest.get("live_rail"),
            "broker_order_routing": str(
                strategy_summary.get("broker_order_routing", "local_paper_only")
            ),
            "strategy_status": str(strategy_summary.get("status", session_state.get("status", "unknown"))),
            "data_source": str(strategy_summary.get("data_source", run_manifest.get("data_source", "unknown"))),
            "simulated_market_data": bool(strategy_summary.get("simulated_market_data", False)),
        },
        "stale_data_count": int(1 if str(safety_summary.get("health_state", "")) == "DATA_STALE" else 0),
        "missing_bars_count": int(safety_summary.get("missing_bars_count", 0) or 0),
        "orders_per_hour": float(orders_per_hour),
        "reject_rate": 0.0,
        "last_bars": last_bars,
        "objectstore_status": str(session_state.get("status", "unknown")),
        "broker_context": broker_context,
        "strategy_summary": strategy_summary,
        "no_trade_summary": no_trade,
    }


def _ui_manifest(
    *,
    run_id: str,
    run_manifest: dict[str, object],
    session_state: dict[str, object],
    strategy_summary: dict[str, object],
    symbols: list[str],
    result: LocalBacktestResult,
) -> dict[str, object]:
    started_at = str(run_manifest.get("startup_time_utc") or session_state.get("started_at_utc") or datetime.now(UTC).isoformat())
    ended_at = str(session_state.get("ended_at_utc") or started_at)
    notes = [
        f"Paper run: {run_id}",
        "Paper strategy artifacts are sourced from this paper run. Routing mode: local_paper_only.",
    ]
    if bool(strategy_summary.get("simulated_market_data", False)):
        notes.append(
            "Paper data source is lean_history synthetic data. Timestamps are current, but market prices are simulated."
        )
    return {
        "run_id": run_id,
        "wf_run_id": None,
        "started_at": started_at,
        "ended_at": ended_at,
        "symbols": symbols,
        "active_symbol": symbols[0] if symbols else "EURUSD",
        "regime": str(strategy_summary.get("last_regime", "TREND") or "TREND"),
        "regime_probabilities": {"TREND": 0.5, "CHOP": 0.3, "RISK_OFF": 0.2},
        "status": f"paper_{session_state.get('status', 'stopped')}",
        "data_profile": str(strategy_summary.get("data_source", run_manifest.get("data_source", "unknown"))),
        "pipeline_version": str(strategy_summary.get("status", "paper")),
        "artifact_context": "paper_strategy",
        "paper_trading_active": True,
        "live_broker": run_manifest.get("live_broker"),
        "live_rail": run_manifest.get("live_rail"),
        "broker_order_routing": str(strategy_summary.get("broker_order_routing", "local_paper_only")),
        "strategy_status": str(strategy_summary.get("status", "completed")),
        "data_source": str(strategy_summary.get("data_source", run_manifest.get("data_source", "unknown"))),
        "simulated_market_data": bool(strategy_summary.get("simulated_market_data", False)),
        "errors": [],
        "warnings": [],
        "notes": notes,
        "metrics": _paper_metrics(result),
    }


def _refresh_completed_ui_snapshot(run_dir: Path, session_state: dict[str, object]) -> None:
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = f"paper_{session_state.get('status', 'stopped')}"
        manifest["ended_at"] = str(session_state.get("ended_at_utc") or manifest.get("ended_at"))
        manifest["strategy_status"] = str(
            (session_state.get("paper_strategy_summary") or {}).get(
                "status",
                manifest.get("strategy_status", session_state.get("status", "unknown")),
            )
        )
        _write_json(manifest_path, manifest)

    paper_ops_path = run_dir / "paper_ops.json"
    if paper_ops_path.exists():
        paper_ops = json.loads(paper_ops_path.read_text(encoding="utf-8"))
        paper_ops["objectstore_status"] = str(session_state.get("status", "unknown"))
        run_manifest = paper_ops.get("run_manifest", {})
        if isinstance(run_manifest, dict):
            run_manifest["strategy_status"] = str(
                (session_state.get("paper_strategy_summary") or {}).get(
                    "status",
                    run_manifest.get("strategy_status", session_state.get("status", "unknown")),
                )
            )
            paper_ops["run_manifest"] = run_manifest
        _write_json(paper_ops_path, paper_ops)


def _write_paper_ui_artifacts(
    *,
    run_dir: Path,
    cfg: EngineConfig,
    run_id: str,
    run_manifest: dict[str, object],
    session_state: dict[str, object],
    aligned: dict[str, pd.DataFrame],
    execution_data: dict[str, pd.DataFrame],
    trend_engine: TrendEngine,
    result: LocalBacktestResult,
    started_at: datetime,
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    strategy_summary: dict[str, object],
    broker_context: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    pairs_diagnostics, pair_history, scans_df, pair_state_events_df = _build_pairs_ui_artifacts(
        cfg=cfg,
        aligned=aligned,
        execution_data=execution_data,
        result=result,
    )
    indicator_snapshots = _build_indicator_snapshots(cfg=cfg, execution_data=execution_data)
    trend_decisions = _build_trend_decisions(
        signals=result.signals,
        indicator_snapshots=indicator_snapshots,
    )
    signals_sample = _build_signals_sample(result.signals)
    trend_model_meta = _build_trend_model_meta(
        cfg=cfg,
        trend_engine=trend_engine,
        started_at=started_at,
    )
    manifest = _ui_manifest(
        run_id=run_id,
        run_manifest=run_manifest,
        session_state=session_state,
        strategy_summary=strategy_summary,
        symbols=all_symbols(cfg),
        result=result,
    )
    paper_ops = _paper_ops_payload(
        run_manifest=run_manifest,
        session_state=session_state,
        strategy_summary=strategy_summary,
        bars=bars,
        orders=orders,
        broker_context=broker_context,
    )
    events = _ops_events_payload(
        regime_posteriors=result.regime_posteriors,
        safety_summary=strategy_summary.get("safety_summary", {}),
        broker_context=broker_context,
    )

    append_pair_scans(run_dir, scans_df, run_id=run_id)
    append_pair_state_events(run_dir, pair_state_events_df, run_id=run_id)
    append_indicator_snapshots(run_dir, indicator_snapshots, run_id=run_id)
    _write_json(run_dir / "pairs_diagnostics.json", pairs_diagnostics)
    _write_json(run_dir / "pair_history.json", pair_history)
    _write_json(run_dir / "signals_sample.json", signals_sample)
    _write_json(run_dir / "trend_model_meta.json", trend_model_meta)
    _write_json(run_dir / "regime_posteriors.json", result.regime_posteriors.to_dict(orient="records"))
    _write_json(run_dir / "engine_allocations.json", result.engine_allocations.to_dict(orient="records"))
    _write_json(run_dir / "manifest.json", manifest)
    _write_json(run_dir / "trades.json", _ui_trades(result.trades))
    _write_json(run_dir / "candles.json", _bars_payload(bars))
    _write_json(run_dir / "equity_curve.json", _equity_payload(result.equity_curve))
    _write_json(run_dir / "events.json", events)
    _write_json(run_dir / "paper_ops.json", paper_ops)
    _write_json(run_dir / "indicator_snapshots.json", _indicator_snapshot_payload(indicator_snapshots))
    _write_json(run_dir / "trend_decisions.json", trend_decisions)
    return pairs_diagnostics, pair_history, trend_decisions, _indicator_snapshot_payload(indicator_snapshots)


def run_strategy_paper_cycle(
    *,
    cfg: EngineConfig,
    run_dir: Path,
    run_id: str,
    symbol_map: dict[str, str],
    started_at: datetime,
    client: Any | None = None,
    account_number: str | None = None,
    live_broker: str | None = None,
    live_rail: str | None = None,
) -> dict[str, object]:
    symbols = all_symbols(cfg)
    start_date, end_date = _recent_window(cfg, now=started_at)
    raw = fetch_multi_symbol(
        symbols=symbols,
        start=start_date,
        end=end_date,
        provider=cfg.data.openbb_provider,
        frequency=cfg.data.bar_frequency,
        source=cfg.data.source,
        seed=cfg.robustness.random_seed,
    )
    if not raw:
        raise RuntimeError("Paper strategy cycle fetched no bars from the configured provider")

    aligned, bar_health = normalize_universe(raw, target_frequency=cfg.data.bar_frequency)
    if not aligned:
        raise RuntimeError("Paper strategy cycle produced no aligned bars")

    test_reference = next(iter(aligned.values())).index
    train_index, test_index = _split_train_test_index(
        pd.DatetimeIndex(test_reference),
        test_window_days=cfg.trend.test_window_days,
    )
    train_start = pd.Timestamp(train_index.min())
    train_end = pd.Timestamp(train_index.max())
    test_start = pd.Timestamp(test_index.min())
    test_end = pd.Timestamp(test_index.max())

    train_data = {
        symbol: frame[(frame.index >= train_start) & (frame.index <= train_end)]
        for symbol, frame in aligned.items()
    }
    execution_data = {
        symbol: frame[(frame.index >= test_start) & (frame.index <= test_end)]
        for symbol, frame in aligned.items()
    }

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

    bars = _long_bars(execution_data)
    features = _features_from_bars(execution_data)
    targets = (
        result.fills.loc[:, ["timestamp", "symbol", "target_weight"]].copy()
        if not result.fills.empty
        else pd.DataFrame(columns=["timestamp", "symbol", "target_weight"])
    )
    orders = _orders_from_fills(result.fills, symbol_map=symbol_map)
    fills = _fills_for_storage(result.fills, symbol_map=symbol_map)

    append_bars(run_dir, bars, run_id=run_id)
    append_features(run_dir, features, run_id=run_id)
    append_signals(run_dir, result.signals, run_id=run_id)
    append_targets(run_dir, targets, run_id=run_id)
    append_orders(run_dir, orders, run_id=run_id)
    append_fills(run_dir, fills, run_id=run_id)
    append_equity_curve(run_dir, result.equity_curve.loc[:, ["timestamp", "equity"]], run_id=run_id)

    risk_rows = [
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "reason": "paper_strategy_cycle_complete",
        }
    ]
    if str(cfg.data.source).strip().lower() == "lean_history":
        risk_rows.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "reason": "paper_strategy_simulated_source",
            }
        )
    append_risk_events(run_dir, pd.DataFrame(risk_rows), run_id=run_id)

    trade_payload = _ui_trades(result.trades)
    _write_json(run_dir / "paper_trades.json", trade_payload)
    _write_json(run_dir / "bar_health.json", bar_health.to_dict(orient="records"))
    position_plan = _paper_position_plan(fills=result.fills, symbols=symbols, symbol_map=symbol_map)
    _write_json(run_dir / "paper_position_plan.json", position_plan)
    ops_summary, _ = generate_ops_summary(run_dir, write=True)
    broker_context, broker_context_events, broker_client, broker_account_number = _collect_broker_context(
        cfg=cfg,
        symbol_map=symbol_map,
        symbols=symbols,
    )
    active_client = client or broker_client
    active_account_number = account_number or broker_account_number
    append_broker_context(run_dir, broker_context_events, run_id=run_id)
    _write_json(run_dir / "broker_context_latest.json", broker_context)
    safety_summary, safety_risk_events, reconciliation_events = _paper_safety_summary(
        cfg=cfg,
        run_id=run_id,
        bars=bars,
        fills=result.fills,
        bar_health=bar_health,
        client=active_client,
        account_number=active_account_number,
        symbol_map=symbol_map,
        symbols=symbols,
    )
    if safety_risk_events:
        append_risk_events(run_dir, pd.DataFrame(safety_risk_events), run_id=run_id)
    append_reconciliation_events(run_dir, reconciliation_events, run_id=run_id)
    last_regime = (
        str(result.regime_posteriors["regime_label"].iloc[-1])
        if not result.regime_posteriors.empty
        else "UNKNOWN"
    )
    rollout_profile = _paper_rollout_profile(cfg=cfg, symbol_map=symbol_map)
    strategy_summary = {
        "status": "completed",
        "execution_window_start": test_start.isoformat(),
        "execution_window_end": test_end.isoformat(),
        "data_source": cfg.data.source,
        "bar_frequency": cfg.data.bar_frequency,
        "simulated_market_data": str(cfg.data.source).strip().lower() == "lean_history",
        "broker_order_routing": "local_paper_only",
        "symbols": symbols,
        "bars_written": int(len(bars)),
        "signals_emitted": int(len(result.signals)),
        "fills_emitted": int(len(fills)),
        "closed_trades": int(len(result.trades)),
        "last_regime": last_regime,
        "last_equity": float(result.equity_curve["equity"].iloc[-1])
        if not result.equity_curve.empty
        else None,
        "position_plan_count": int(len(position_plan)),
        "active_position_count": int(
            sum(1 for row in position_plan if row["direction"] != "flat")
        ),
        "contract_ready_position_count": int(
            sum(1 for row in position_plan if row["orderable_contract_ready"])
        ),
        "paper_rollout_profile": rollout_profile,
        "safety_summary": safety_summary,
        "ops_summary": ops_summary,
        "metrics": _paper_metrics(result),
        "broker_context": broker_context,
    }
    _write_json(run_dir / "paper_strategy_summary.json", strategy_summary)
    _write_json(run_dir / "paper_safety_summary.json", safety_summary)
    append_broker_events(
        run_dir,
        [
            {
                "event": "strategy_cycle_complete",
                "run_id": run_id,
                "rail": live_rail or "local_paper",
                "broker": live_broker or "local",
                "data_source": cfg.data.source,
                "bar_frequency": cfg.data.bar_frequency,
                "broker_order_routing": "local_paper_only",
                "signals_emitted": int(len(result.signals)),
                "fills_emitted": int(len(fills)),
                "closed_trades": int(len(result.trades)),
                "execution_window_start": test_start.isoformat(),
                "execution_window_end": test_end.isoformat(),
                "active_position_count": int(
                    sum(1 for row in position_plan if row["direction"] != "flat")
                ),
                "close_only": bool(safety_summary["close_only"]),
                "health_state": safety_summary["health_state"],
            }
        ],
        run_id=run_id,
    )
    _update_run_manifest(
        run_dir,
        {
            "paper_strategy_status": "completed",
            "paper_broker_order_routing": "local_paper_only",
            "paper_data_source": cfg.data.source,
            "paper_execution_window_start": test_start.isoformat(),
            "paper_execution_window_end": test_end.isoformat(),
            "paper_position_plan_generated": True,
            "paper_health_state": safety_summary["health_state"],
            "paper_close_only": bool(safety_summary["close_only"]),
        },
    )
    current_run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    current_session_state = json.loads((run_dir / "session_state.json").read_text(encoding="utf-8"))
    pairs_diagnostics, _, _, indicator_payload = _write_paper_ui_artifacts(
        run_dir=run_dir,
        cfg=cfg,
        run_id=run_id,
        run_manifest=current_run_manifest,
        session_state=current_session_state,
        aligned=aligned,
        execution_data=execution_data,
        trend_engine=trend_engine,
        result=result,
        started_at=started_at,
        bars=bars,
        orders=orders,
        strategy_summary=strategy_summary,
        broker_context=broker_context,
    )
    strategy_summary["no_trade_diagnostics"] = _no_trade_diagnostics(
        symbols=symbols,
        symbol_map=symbol_map,
        pairs_diagnostics=pairs_diagnostics,
        signals=result.signals,
        result=result,
        safety_summary=safety_summary,
        bar_health=bar_health,
    )
    _write_json(run_dir / "paper_strategy_summary.json", strategy_summary)
    _write_json(
        run_dir / "paper_ops.json",
        _paper_ops_payload(
            run_manifest=current_run_manifest,
            session_state=current_session_state,
            strategy_summary=strategy_summary,
            bars=bars,
            orders=orders,
            broker_context=broker_context,
        ),
    )
    _write_json(run_dir / "indicator_snapshots.json", indicator_payload)
    return strategy_summary


def run_local_paper_session(
    *,
    cfg: EngineConfig,
    config_path: str | Path,
    run_id: str | None = None,
    output_dir: str | Path | None = None,
    run_seconds: int = 0,
) -> Path:
    cfg_payload = asdict(cfg)
    cfg_hash = hash_config(cfg_payload)
    now = datetime.now(UTC)
    resolved_run_id = run_id or make_run_id(now, cfg_hash)
    run_dir = (
        Path(output_dir)
        if output_dir
        else build_run_dir(cfg.ops.output_root, mode="paper", run_id=resolved_run_id)
    )
    symbols = all_symbols(cfg)
    symbol_map = preview_symbol_map(cfg, symbols)

    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": resolved_run_id,
        "mode": "paper",
        "config_path": str(Path(config_path).resolve()),
        "git_commit": resolve_git_commit(),
        "config_hash": cfg_hash,
        "schema_version": SCHEMA_VERSION,
        "seed": int(cfg.robustness.random_seed),
        "bar_frequency": cfg.data.bar_frequency,
        "data_source": cfg.data.source,
        "live_rail": "local_paper",
        "live_broker": "local",
        "symbols": symbols,
        "startup_time_utc": now.isoformat(),
        "runtime_toggles": {
            "precompute_enabled": None,
            "mode_reuse_enabled": None,
        },
        "ladder_stage": normalize_stage(cfg.micro_live_ladder.active_stage),
        "ladder_caps": asdict(resolve_ladder_caps(stage=cfg.micro_live_ladder.active_stage)),
        "local_paper": {
            "symbol_map_preview": symbol_map,
        },
    }
    initialize_run_metadata(run_dir, run_manifest=manifest, config_snapshot={"config": cfg_payload})
    write_empty_streams(run_dir, empty_stream_frames(resolved_run_id), run_id=resolved_run_id)

    append_broker_events(
        run_dir,
        [
            {
                "event": "session_start",
                "run_id": resolved_run_id,
                "rail": "local_paper",
                "broker": "local",
                "symbols": symbols,
                "bar_frequency": cfg.data.bar_frequency,
                "data_source": cfg.data.source,
            }
        ],
        run_id=resolved_run_id,
    )

    state_path = run_dir / "session_state.json"
    session_state = {
        "run_id": resolved_run_id,
        "status": "running",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "broker": "local",
        "rail": "local_paper",
        "paper_strategy_status": "pending",
    }
    write_session_state(state_path, session_state)

    status = "running"
    try:
        strategy_summary = run_strategy_paper_cycle(
            cfg=cfg,
            run_dir=run_dir,
            run_id=resolved_run_id,
            symbol_map=symbol_map,
            started_at=now,
            client=None,
            account_number=None,
            live_broker="local",
            live_rail="local_paper",
        )
        session_state["paper_strategy_status"] = str(strategy_summary.get("status", "completed"))
        session_state["paper_strategy_summary"] = strategy_summary
        session_state["last_regime"] = strategy_summary.get("last_regime", "UNKNOWN")
        session_state["close_only"] = bool(
            strategy_summary.get("safety_summary", {}).get("close_only", False)
        )
        session_state["health_state"] = strategy_summary.get("safety_summary", {}).get(
            "health_state", "UNKNOWN"
        )
        write_session_state(state_path, session_state)
        if run_seconds > 0:
            deadline = time.time() + run_seconds
            while time.time() < deadline:
                time.sleep(1)
                append_broker_events(
                    run_dir,
                    [
                        {
                            "event": "heartbeat",
                            "run_id": resolved_run_id,
                            "rail": "local_paper",
                            "broker": "local",
                        }
                    ],
                    run_id=resolved_run_id,
                )
        status = "stopped"
    except KeyboardInterrupt:
        status = "interrupted"
    except Exception as exc:
        status = "error"
        append_broker_events(
            run_dir,
            [
                {
                    "event": "session_error",
                    "run_id": resolved_run_id,
                    "rail": "local_paper",
                    "broker": "local",
                    "message": str(exc),
                }
            ],
            run_id=resolved_run_id,
        )
        raise
    finally:
        session_state["status"] = status
        session_state["ended_at_utc"] = datetime.now(UTC).isoformat()
        write_session_state(state_path, session_state)
        _refresh_completed_ui_snapshot(run_dir, session_state)
        append_broker_events(
            run_dir,
            [
                {
                    "event": "session_stop",
                    "run_id": resolved_run_id,
                    "status": status,
                    "rail": "local_paper",
                    "broker": "local",
                }
            ],
            run_id=resolved_run_id,
        )
    return run_dir
