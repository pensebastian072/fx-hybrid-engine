"""Tastytrade live-session scaffold backed by ops artifacts."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from fx_hybrid_engine.brokers.base import BrokerAccount, BrokerBalance, BrokerOrderRequest
from fx_hybrid_engine.brokers.tastytrade import TastytradeApiClient, TastytradeCredentials
from fx_hybrid_engine.contracts import SCHEMA_VERSION
from fx_hybrid_engine.data.alignment import normalize_universe
from fx_hybrid_engine.data.provider import fetch_multi_symbol
from fx_hybrid_engine.engines.pairs import PairsEngine
from fx_hybrid_engine.engines.trend import TrendEngine
from fx_hybrid_engine.evaluation.local_backtester import run_local_backtest
from fx_hybrid_engine.evaluation.phase1_runner import (
    _features_from_bars,
    _fit_hmm_from_training,
    _long_bars,
    _train_trend_safely,
)
from fx_hybrid_engine.lean.runtime_safety import evaluate_runtime_safety
from fx_hybrid_engine.ops.circuit_breakers import BreakerContext
from fx_hybrid_engine.ops.health import HealthPolicy
from fx_hybrid_engine.ops.ladder import normalize_stage, resolve_ladder_caps
from fx_hybrid_engine.ops.layout import build_run_dir
from fx_hybrid_engine.ops.ops_summary import generate_ops_summary
from fx_hybrid_engine.ops.local_paper import run_strategy_paper_cycle as run_shared_strategy_paper_cycle
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
from fx_hybrid_engine.regime.orchestrator import RegimeOrchestrator
from fx_hybrid_engine.utils.config import EngineConfig, TastytradeConfig
from fx_hybrid_engine.utils.identity import hash_config, make_run_id, resolve_git_commit


def _empty_stream_frames(run_id: str) -> dict[str, pd.DataFrame]:
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


def _all_symbols(cfg: EngineConfig) -> list[str]:
    return sorted({s for pair in cfg.pair_list for s in pair} | set(cfg.trend_symbols))


def _normalized_symbol_map(cfg: EngineConfig, symbols: list[str]) -> dict[str, str]:
    raw_map = cfg.tastytrade.symbol_map or {}
    normalized = {symbol: str(raw_map.get(symbol, "")).strip() for symbol in symbols}
    missing = sorted(symbol for symbol, mapped in normalized.items() if not mapped)
    if cfg.tastytrade.require_symbol_map and missing:
        raise ValueError("Tastytrade symbol_map is missing mappings for: " + ", ".join(missing))
    return {symbol: mapped for symbol, mapped in normalized.items() if mapped}


def _build_tastytrade_client(cfg: TastytradeConfig) -> TastytradeApiClient:
    creds = TastytradeCredentials(
        client_id=os.environ[cfg.client_id_env],
        client_secret=os.environ[cfg.client_secret_env],
        refresh_token=os.environ[cfg.refresh_token_env],
    )
    return TastytradeApiClient(
        credentials=creds,
        oauth_token_url=cfg.oauth_token_url,
        accounts_url=cfg.accounts_url,
        balances_url_template=cfg.balances_url_template,
    )


def _resolve_account_number(cfg: TastytradeConfig, accounts: list[BrokerAccount]) -> str:
    selected = str(os.getenv(cfg.account_number_env, "")).strip()
    available = [account.account_number for account in accounts]
    if selected:
        if selected not in available:
            raise ValueError(
                f"Tastytrade account '{selected}' was not returned by the API. "
                f"Available accounts: {available}"
            )
        return selected
    if len(available) == 1:
        return available[0]
    raise ValueError(
        f"Multiple Tastytrade accounts are available. Set {cfg.account_number_env} to choose one."
    )


def _write_empty_streams(run_dir: Path, frames: dict[str, pd.DataFrame], *, run_id: str) -> None:
    append_bars(run_dir, frames["bars"], run_id=run_id)
    append_features(run_dir, frames["features"], run_id=run_id)
    append_signals(run_dir, frames["signals"], run_id=run_id)
    append_targets(run_dir, frames["targets"], run_id=run_id)
    append_orders(run_dir, frames["orders"], run_id=run_id)
    append_fills(run_dir, frames["fills"], run_id=run_id)
    append_equity_curve(run_dir, frames["equity_curve"], run_id=run_id)
    append_risk_events(run_dir, frames["risk_events"], run_id=run_id)
    append_reconciliation_events(run_dir, [], run_id=run_id)


def _write_session_state(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _balance_event(
    *,
    event: str,
    account_number: str,
    balance: BrokerBalance,
    rail: str,
    broker: str,
) -> dict[str, object]:
    return {
        "event": event,
        "account_number": account_number,
        "rail": rail,
        "broker": broker,
        "balance": balance.raw,
    }


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
    client: TastytradeApiClient | None,
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
        "missing_bars_count": missing_bars,
        "latest_bar_timestamp": latest_bar_timestamp,
    }
    if snapshot.reconciliation is not None:
        summary["reconciliation"] = asdict(snapshot.reconciliation)
    return summary, snapshot.risk_events, reconciliation_events


def _run_strategy_paper_cycle(
    *,
    cfg: EngineConfig,
    run_dir: Path,
    run_id: str,
    symbol_map: dict[str, str],
    started_at: datetime,
    client: TastytradeApiClient | None = None,
    account_number: str | None = None,
) -> dict[str, object]:
    return run_shared_strategy_paper_cycle(
        cfg=cfg,
        run_dir=run_dir,
        run_id=run_id,
        symbol_map=symbol_map,
        started_at=started_at,
        client=client,
        account_number=account_number,
        live_broker=cfg.live_execution.broker,
        live_rail=cfg.live_execution.rail,
    )


def _native_order_requests(
    *,
    run_id: str,
    account_number: str,
    symbol_map: dict[str, str],
    payload: dict[str, object],
) -> list[BrokerOrderRequest]:
    intents = payload.get("native_order_intents")
    if not isinstance(intents, list):
        return []
    requests: list[BrokerOrderRequest] = []
    for intent in intents:
        if not isinstance(intent, dict):
            continue
        raw_symbol = str(intent.get("symbol", "")).strip()
        side = str(intent.get("side", "")).strip().lower()
        quantity_raw = intent.get("quantity", 0.0)
        try:
            quantity = float(quantity_raw)
        except (TypeError, ValueError):
            continue
        broker_symbol = symbol_map.get(raw_symbol, raw_symbol)
        if not broker_symbol or side not in {"buy", "sell"} or quantity <= 0:
            continue
        requests.append(
            BrokerOrderRequest(
                account_number=account_number,
                symbol=broker_symbol,
                side=side,
                quantity=quantity,
                order_type=str(intent.get("order_type", "market")),
                raw={
                    "source_symbol": raw_symbol,
                    "run_id": run_id,
                },
            )
        )
    return requests


def _run_broker_native_cycle(
    *,
    cfg: EngineConfig,
    run_dir: Path,
    run_id: str,
    symbol_map: dict[str, str],
    started_at: datetime,
    client: TastytradeApiClient,
    account_number: str,
    strategy_runner: Callable[..., dict[str, object]] | None,
) -> dict[str, object]:
    broker_symbols = sorted({mapped for mapped in symbol_map.values() if str(mapped).strip()})
    quotes = client.get_market_quotes(broker_symbols)
    summary: dict[str, object] = {
        "status": "completed",
        "mode": "broker_native_live",
        "market_data_source": "broker_api",
        "market_data_symbols": broker_symbols,
        "market_data_points": len(quotes),
        "order_submission_mode": "broker_native",
        "order_intents": 0,
        "orders_submitted": 0,
    }

    append_broker_events(
        run_dir,
        [
            {
                "event": "broker_market_data_snapshot",
                "run_id": run_id,
                "rail": cfg.live_execution.rail,
                "broker": cfg.live_execution.broker,
                "account_number": account_number,
                "symbols": broker_symbols,
                "quotes_count": len(quotes),
            }
        ],
        run_id=run_id,
    )

    native_payload: dict[str, object] = {}
    if strategy_runner is not None:
        native_payload = strategy_runner(
            cfg=cfg,
            run_dir=run_dir,
            run_id=run_id,
            symbol_map=symbol_map,
            started_at=started_at,
            client=client,
            account_number=account_number,
            mode="broker_native_live",
            market_quotes=quotes,
        )

    order_requests = _native_order_requests(
        run_id=run_id,
        account_number=account_number,
        symbol_map=symbol_map,
        payload=native_payload,
    )
    summary["order_intents"] = len(order_requests)
    if order_requests:
        order_rows: list[dict[str, object]] = []
        broker_events: list[dict[str, object]] = []
        for request in order_requests:
            response = client.submit_order(request)
            order_rows.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "symbol": str(request.raw.get("source_symbol", request.symbol)),
                    "order_type": f"broker_{request.order_type}_{request.side}",
                    "broker_symbol": request.symbol,
                    "account_number": request.account_number,
                    "quantity": request.quantity,
                }
            )
            broker_events.append(
                {
                    "event": "broker_order_submitted",
                    "run_id": run_id,
                    "rail": cfg.live_execution.rail,
                    "broker": cfg.live_execution.broker,
                    "account_number": request.account_number,
                    "symbol": request.raw.get("source_symbol", request.symbol),
                    "broker_symbol": request.symbol,
                    "side": request.side,
                    "quantity": request.quantity,
                    "response": response,
                }
            )
        append_orders(run_dir, pd.DataFrame(order_rows), run_id=run_id)
        append_broker_events(run_dir, broker_events, run_id=run_id)
    summary["orders_submitted"] = len(order_requests)

    _write_json(run_dir / "broker_native_summary.json", summary)
    _update_run_manifest(
        run_dir,
        {
            "broker_order_routing": "broker_native",
            "broker_market_data_source": "tastytrade_api",
            "broker_native_summary": summary,
        },
    )
    return summary


def run_tastytrade_live_session(
    *,
    cfg: EngineConfig,
    config_path: str | Path,
    run_id: str | None = None,
    output_dir: str | Path | None = None,
    mode: str | None = None,
    run_seconds: int = 0,
    client_builder: Callable[[TastytradeConfig], TastytradeApiClient] | None = None,
    strategy_runner: Callable[..., dict[str, object]] | None = None,
) -> Path:
    """Start a broker-backed Tastytrade session scaffold and emit ops artifacts."""
    cfg_payload = asdict(cfg)
    cfg_hash = hash_config(cfg_payload)
    now = datetime.now(UTC)
    resolved_run_id = run_id or make_run_id(now, cfg_hash)
    resolved_mode = mode or cfg.ops.mode
    run_dir = (
        Path(output_dir)
        if output_dir
        else build_run_dir(cfg.ops.output_root, mode=resolved_mode, run_id=resolved_run_id)
    )

    symbols = _all_symbols(cfg)
    symbol_map = _normalized_symbol_map(cfg, symbols)
    builder = client_builder or _build_tastytrade_client
    client = builder(cfg.tastytrade)
    accounts = client.list_accounts()
    account_number = _resolve_account_number(cfg.tastytrade, accounts)
    balance = client.get_balances(account_number)

    run_dir.mkdir(parents=True, exist_ok=True)
    broker_native_requested = (
        str(cfg.live_execution.rail).strip().lower() == "tastytrade_live"
    )
    broker_native_enabled = (
        broker_native_requested
        and bool(cfg.live_execution.enable_broker_native_orders)
        and bool(cfg.live_execution.enable_broker_market_data)
    )
    manifest = {
        "run_id": resolved_run_id,
        "mode": resolved_mode,
        "config_path": str(Path(config_path).resolve()),
        "git_commit": resolve_git_commit(),
        "config_hash": cfg_hash,
        "schema_version": SCHEMA_VERSION,
        "seed": int(cfg.robustness.random_seed),
        "bar_frequency": cfg.data.bar_frequency,
        "data_source": cfg.data.source,
        "live_rail": cfg.live_execution.rail,
        "live_broker": cfg.live_execution.broker,
        "symbols": symbols,
        "startup_time_utc": now.isoformat(),
        "runtime_toggles": {
            "precompute_enabled": None,
            "mode_reuse_enabled": None,
            "broker_native_orders_enabled": bool(cfg.live_execution.enable_broker_native_orders),
            "broker_market_data_enabled": bool(cfg.live_execution.enable_broker_market_data),
        },
        "ladder_stage": normalize_stage(cfg.micro_live_ladder.active_stage),
        "ladder_caps": asdict(resolve_ladder_caps(stage=cfg.micro_live_ladder.active_stage)),
        "tastytrade": {
            "account_number": account_number,
            "api_base_url": cfg.tastytrade.api_base_url,
            "symbol_map": symbol_map,
        },
        "broker_order_routing": "broker_native" if broker_native_enabled else "local_paper_only",
        "broker_market_data_source": "tastytrade_api" if broker_native_enabled else "local_provider",
    }
    initialize_run_metadata(run_dir, run_manifest=manifest, config_snapshot={"config": cfg_payload})
    _write_empty_streams(run_dir, _empty_stream_frames(resolved_run_id), run_id=resolved_run_id)

    append_broker_events(
        run_dir,
        [
            {
                "event": "session_start",
                "run_id": resolved_run_id,
                "rail": cfg.live_execution.rail,
                "broker": cfg.live_execution.broker,
                "symbols": symbols,
                "symbol_map": symbol_map,
                "bar_frequency": cfg.data.bar_frequency,
                "data_source": cfg.data.source,
                "account_number": account_number,
            },
            {
                "event": "account_resolved",
                "run_id": resolved_run_id,
                "rail": cfg.live_execution.rail,
                "broker": cfg.live_execution.broker,
                "account_number": account_number,
                "available_accounts": [account.account_number for account in accounts],
            },
            _balance_event(
                event="balance_snapshot",
                account_number=account_number,
                balance=balance,
                rail=cfg.live_execution.rail,
                broker=cfg.live_execution.broker,
            ),
        ],
        run_id=resolved_run_id,
    )

    state_path = run_dir / "session_state.json"
    session_state = {
        "run_id": resolved_run_id,
        "status": "running",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "broker": cfg.live_execution.broker,
        "rail": cfg.live_execution.rail,
        "account_number": account_number,
        "paper_strategy_status": "pending" if resolved_mode == "paper" else "skipped",
        "broker_native_status": "pending" if (resolved_mode == "live" and broker_native_enabled) else "skipped",
    }
    _write_session_state(state_path, session_state)

    status = "running"
    try:
        if resolved_mode == "paper":
            runner = strategy_runner or _run_strategy_paper_cycle
            strategy_summary = runner(
                cfg=cfg,
                run_dir=run_dir,
                run_id=resolved_run_id,
                symbol_map=symbol_map,
                started_at=now,
                client=client,
                account_number=account_number,
            )
            session_state["paper_strategy_status"] = str(
                strategy_summary.get("status", "completed")
            )
            session_state["paper_strategy_summary"] = strategy_summary
            session_state["last_regime"] = strategy_summary.get("last_regime", "UNKNOWN")
            session_state["close_only"] = bool(
                strategy_summary.get("safety_summary", {}).get("close_only", False)
            )
            session_state["health_state"] = strategy_summary.get("safety_summary", {}).get(
                "health_state", "UNKNOWN"
            )
            _write_session_state(state_path, session_state)
        elif resolved_mode == "live" and broker_native_enabled:
            native_summary = _run_broker_native_cycle(
                cfg=cfg,
                run_dir=run_dir,
                run_id=resolved_run_id,
                symbol_map=symbol_map,
                started_at=now,
                client=client,
                account_number=account_number,
                strategy_runner=strategy_runner,
            )
            session_state["broker_native_status"] = str(native_summary.get("status", "completed"))
            session_state["broker_native_summary"] = native_summary
            _write_session_state(state_path, session_state)
        if run_seconds > 0:
            next_balance_refresh = time.time() + 15
            deadline = time.time() + run_seconds
            while time.time() < deadline:
                time.sleep(1)
                append_broker_events(
                    run_dir,
                    [
                        {
                            "event": "heartbeat",
                            "run_id": resolved_run_id,
                            "rail": cfg.live_execution.rail,
                            "broker": cfg.live_execution.broker,
                            "account_number": account_number,
                        }
                    ],
                    run_id=resolved_run_id,
                )
                if time.time() >= next_balance_refresh:
                    latest_balance = client.get_balances(account_number)
                    append_broker_events(
                        run_dir,
                        [
                            _balance_event(
                                event="balance_snapshot",
                                account_number=account_number,
                                balance=latest_balance,
                                rail=cfg.live_execution.rail,
                                broker=cfg.live_execution.broker,
                            )
                        ],
                        run_id=resolved_run_id,
                    )
                    next_balance_refresh = time.time() + 15
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
                    "rail": cfg.live_execution.rail,
                    "broker": cfg.live_execution.broker,
                    "account_number": account_number,
                    "message": str(exc),
                }
            ],
            run_id=resolved_run_id,
        )
        raise
    finally:
        session_state["status"] = status
        session_state["ended_at_utc"] = datetime.now(UTC).isoformat()
        _write_session_state(state_path, session_state)
        append_broker_events(
            run_dir,
            [
                {
                    "event": "session_stop",
                    "run_id": resolved_run_id,
                    "status": status,
                    "rail": cfg.live_execution.rail,
                    "broker": cfg.live_execution.broker,
                    "account_number": account_number,
                }
            ],
            run_id=resolved_run_id,
        )
    return run_dir
