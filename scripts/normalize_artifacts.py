#!/usr/bin/env python3
"""
normalize_artifacts.py

Reads the most recent walkforward + paper run artifacts from:
  - artifacts/walkforward/<latest_wf_run_id>/
  - outputs/paper/<latest_date>/<latest_paper_run_id>/

And produces a normalized JSON set at artifacts/latest_run/:
  - manifest.json  (UI RunManifest schema)
  - trades.json    (UI Trade[] schema)
  - candles.json   (UI Candle[] OHLCV - sourced from parquet bars if available)
  - equity_curve.json (UI EquityPoint[])

Usage:
    python scripts/normalize_artifacts.py [--wf-run-id WF_RUN_ID] [--paper-run-dir DIR] [--out-dir DIR]
"""

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


def find_latest_dir(base: Path) -> Path | None:
    """Return the most recently modified sub-directory under base."""
    if not base.exists():
        return None
    dirs = [d for d in base.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


def find_latest_paper_run(outputs_paper: Path) -> Path | None:
    """Walk outputs/paper/<date>/<run_id>/ and prefer completed strategy runs."""
    if not outputs_paper.exists():
        return None
    all_runs: list[Path] = []
    for date_dir in outputs_paper.iterdir():
        if date_dir.is_dir():
            for run_dir in date_dir.iterdir():
                if run_dir.is_dir():
                    all_runs.append(run_dir)
    if not all_runs:
        return None
    return max(
        all_runs,
        key=lambda d: (
            1 if (d / "paper_strategy_summary.json").exists() else 0,
            1 if (d / "session_state.json").exists() else 0,
            d.stat().st_mtime,
        ),
    )


def read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_json_object(path: Path) -> dict | None:
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def read_json_list(path: Path) -> list[dict]:
    payload = read_json(path)
    if isinstance(payload, list):
        return payload
    return []


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def read_jsonl_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def normalize_timestamp_utc_iso(value: object) -> str:
    """Normalize timestamp-like values to ISO-8601 UTC strings."""
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return ""

    if pd.isna(ts):
        return ""

    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    # Keep explicit UTC designator for UI parsing consistency.
    return ts.isoformat().replace("+00:00", "Z")


def _paper_run_artifact_context(
    paper_manifest: dict | None,
    session_state: dict | None,
    strategy_summary: dict | None,
) -> str:
    if not paper_manifest:
        return "historical_walkforward"
    if strategy_summary:
        return "paper_strategy"
    if session_state:
        return "paper_scaffold"
    return "historical_walkforward"


def _paper_trade_fallback(fills: pd.DataFrame) -> list[dict]:
    if fills.empty:
        return []
    rows: list[dict] = []
    for idx, row in fills.iterrows():
        fill_price = row.get("fill_price", row.get("price"))
        if pd.isna(fill_price):
            fill_price = 0.0
        fill_price = float(fill_price or 0.0)
        delta_weight = float(row.get("delta_weight", 0.0) or 0.0)
        side = "long" if delta_weight >= 0 else "short"
        if side == "long":
            stop = fill_price * 0.995 if fill_price else 0.0
            take_profit = fill_price * 1.01 if fill_price else 0.0
        else:
            stop = fill_price * 1.005 if fill_price else 0.0
            take_profit = fill_price * 0.99 if fill_price else 0.0
        engine_source = str(row.get("engine_source", "trend") or "trend")
        rows.append(
            {
                "id": f"paper_fill_{idx + 1:04d}",
                "time": str(row.get("timestamp", "")),
                "exit_time": None,
                "symbol": str(row.get("symbol", "")),
                "engine_source": engine_source,
                "side": side,
                "entry": fill_price,
                "exit": None,
                "stop": stop,
                "take_profit": take_profit,
                "size": abs(float(row.get("target_weight", delta_weight) or 0.0)),
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "close_reason": None,
                "regime_at_entry": str(row.get("regime_label", "TREND") or "TREND"),
                "tags": [engine_source],
            }
        )
    return rows


def normalize_paper_trades(paper_dir: Path | None) -> list[dict]:
    if not paper_dir:
        return []
    paper_trades = read_json(paper_dir / "paper_trades.json")
    if isinstance(paper_trades, list):
        return paper_trades
    fills = read_parquet(paper_dir / "fills.parquet")
    return _paper_trade_fallback(fills)


def normalize_paper_candles(paper_dir: Path | None, symbol: str) -> list[dict]:
    if not paper_dir:
        return []
    bars = read_parquet(paper_dir / "bars.parquet")
    if bars.empty:
        return []
    if "symbol" in bars.columns:
        bars = bars[bars["symbol"].astype(str) == symbol]
    if bars.empty:
        return []
    candles: list[dict] = []
    for _, row in bars.sort_values("timestamp").iterrows():
        ts = normalize_timestamp_utc_iso(row.get("timestamp", ""))
        if not ts:
            continue
        candles.append(
            {
                "time": ts,
                "open": float(row.get("open", row.get("close", 0.0)) or 0.0),
                "high": float(row.get("high", row.get("close", 0.0)) or 0.0),
                "low": float(row.get("low", row.get("close", 0.0)) or 0.0),
                "close": float(row.get("close", 0.0) or 0.0),
                "volume": float(row.get("volume", 0.0) or 0.0),
                "symbol": str(row.get("symbol", symbol)),
            }
        )
    return candles


def normalize_paper_equity(paper_dir: Path | None) -> tuple[list[dict], pd.DataFrame]:
    if not paper_dir:
        return [], pd.DataFrame()
    equity = read_parquet(paper_dir / "equity_curve.parquet")
    if equity.empty:
        return [], equity
    points = []
    for _, row in equity.sort_values("timestamp").iterrows():
        points.append(
            {
                "timestamp": str(row.get("timestamp", "")),
                "equity": float(row.get("equity", 0.0) or 0.0),
                "regime_label": str(row.get("regime_label", "TREND") or "TREND"),
            }
        )
    return points, equity


def normalize_paper_events(paper_dir: Path | None) -> list[dict]:
    now = datetime.now(UTC).isoformat()
    if not paper_dir:
        return [
            {
                "timestamp": now,
                "event_type": "deploy_change",
                "message": "No paper run has been normalized into artifacts/latest_run yet.",
            }
        ]

    broker_events = read_jsonl_rows(paper_dir / "broker_events.jsonl")
    risk_events = read_parquet(paper_dir / "risk_events.parquet")
    events: list[dict] = []
    for row in broker_events:
        event_name = str(row.get("event", "broker_event") or "broker_event")
        events.append(
            {
                "timestamp": str(row.get("timestamp", now)),
                "event_type": "deploy_change",
                "message": event_name.replace("_", " "),
                "action": str(row.get("broker_order_routing", "")) or None,
            }
        )
    if not risk_events.empty:
        for _, row in risk_events.iterrows():
            events.append(
                {
                    "timestamp": str(row.get("timestamp", now)),
                    "event_type": "risk_event",
                    "message": str(row.get("reason", "risk event")),
                }
            )
    if not events:
        return [
            {
                "timestamp": now,
                "event_type": "deploy_change",
                "message": "Paper run is present but has not emitted broker or risk events yet.",
            }
        ]
    return sorted(events, key=lambda row: str(row.get("timestamp", now)))


def _paper_metrics(trades: list[dict], equity: pd.DataFrame, ops_summary: dict | None) -> dict[str, float]:
    pnl_values = [float(row.get("pnl", 0.0) or 0.0) for row in trades]
    total_return = 0.0
    max_drawdown = 0.0
    if not equity.empty and "equity" in equity.columns:
        equity_series = equity["equity"].astype(float)
        total_return = float(equity_series.iloc[-1] - equity_series.iloc[0]) if len(equity_series) > 1 else 0.0
    if isinstance(ops_summary, dict):
        max_drawdown = float(ops_summary.get("max_drawdown", 0.0) or 0.0)
    wins = sum(1 for value in pnl_values if value > 0)
    return {
        "sharpe_ratio": 0.0,
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "win_rate": float(wins / len(pnl_values)) if pnl_values else 0.0,
        "num_trades": int(len(pnl_values)),
        "avg_trade_pnl": float(sum(pnl_values) / len(pnl_values)) if pnl_values else 0.0,
    }


def normalize_paper_ops(
    paper_dir: Path | None,
    *,
    manifest: dict | None,
    session_state: dict | None,
    strategy_summary: dict | None,
) -> dict:
    now = datetime.now(UTC).isoformat()
    if not paper_dir or not manifest:
        return {
            "run_manifest": {
                "run_id": manifest.get("run_id", "no_paper_run") if isinstance(manifest, dict) else "no_paper_run",
                "git_commit": manifest.get("git_commit", "unknown") if isinstance(manifest, dict) else "unknown",
                "config_hash": manifest.get("config_hash", "unknown") if isinstance(manifest, dict) else "unknown",
                "schema_version": manifest.get("schema_version", "1.0.0") if isinstance(manifest, dict) else "1.0.0",
                "created_at_utc": now,
                "seed": int(manifest.get("seed", 0) or 0) if isinstance(manifest, dict) else 0,
                "precompute_enabled": False,
                "mode_reuse_enabled": False,
                "data_profile": manifest.get("data_profile", "not_started") if isinstance(manifest, dict) else "not_started",
                "pipeline_version": manifest.get("pipeline_version", "not_started") if isinstance(manifest, dict) else "not_started",
                "live_broker": manifest.get("live_broker") if isinstance(manifest, dict) else None,
                "live_rail": manifest.get("live_rail") if isinstance(manifest, dict) else None,
                "broker_order_routing": "not_started",
                "strategy_status": "not_started",
                "data_source": manifest.get("data_source", "unknown") if isinstance(manifest, dict) else "unknown",
                "simulated_market_data": False,
            },
            "stale_data_count": 0,
            "missing_bars_count": 0,
            "orders_per_hour": 0.0,
            "reject_rate": 0.0,
            "last_bars": [],
            "objectstore_status": "no_paper_run",
        }

    ops_summary = read_json(paper_dir / "ops_summary.json")
    bars = read_parquet(paper_dir / "bars.parquet")
    orders = read_parquet(paper_dir / "orders.parquet")
    bar_health = read_json(paper_dir / "bar_health.json")
    missing_bars = 0
    if isinstance(bar_health, list):
        for row in bar_health:
            try:
                missing_bars += int(row.get("gap_count", 0) or 0)
            except Exception:
                continue
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
            orders_per_hour = float(len(parsed))
    reject_count = float(ops_summary.get("reject_count", 0.0) or 0.0) if isinstance(ops_summary, dict) else 0.0
    reject_rate = float(reject_count / len(orders)) if len(orders) else 0.0
    runtime_toggles = manifest.get("runtime_toggles", {}) if isinstance(manifest, dict) else {}
    return {
        "run_manifest": {
            "run_id": str(manifest.get("run_id", paper_dir.name)),
            "git_commit": str(manifest.get("git_commit", "unknown")),
            "config_hash": str(manifest.get("config_hash", "unknown")),
            "schema_version": str(manifest.get("schema_version", "1.0.0")),
            "created_at_utc": str(
                manifest.get("startup_time_utc")
                or (session_state or {}).get("started_at_utc")
                or now
            ),
            "seed": int(manifest.get("seed", 0) or 0),
            "precompute_enabled": bool(runtime_toggles.get("precompute_enabled", False)),
            "mode_reuse_enabled": bool(runtime_toggles.get("mode_reuse_enabled", False)),
            "data_profile": str(manifest.get("data_source", "paper")),
            "pipeline_version": str((strategy_summary or {}).get("status", "paper")),
            "live_broker": manifest.get("live_broker"),
            "live_rail": manifest.get("live_rail"),
            "broker_order_routing": str((strategy_summary or {}).get("broker_order_routing", "scaffold_only")),
            "strategy_status": str((strategy_summary or {}).get("status", (session_state or {}).get("status", "unknown"))),
            "data_source": str((strategy_summary or {}).get("data_source", manifest.get("data_source", "unknown"))),
            "simulated_market_data": bool((strategy_summary or {}).get("simulated_market_data", False)),
        },
        "stale_data_count": int((ops_summary or {}).get("stale_event_count", 0) if isinstance(ops_summary, dict) else 0),
        "missing_bars_count": int(missing_bars),
        "orders_per_hour": orders_per_hour,
        "reject_rate": reject_rate,
        "last_bars": last_bars,
        "objectstore_status": str((session_state or {}).get("status", "unknown")),
    }

def normalize_manifest(
    wf_manifest: dict | None,
    paper_manifest: dict | None,
    paper_session_state: dict | None,
    paper_strategy_summary: dict | None,
    wf_run_id: str,
    errors: list,
    warnings: list,
    notes: list,
) -> dict:
    artifact_context = _paper_run_artifact_context(
        paper_manifest,
        paper_session_state,
        paper_strategy_summary,
    )
    started_at = datetime.now(UTC).isoformat()
    ended_at = started_at

    if paper_manifest:
        started_at = str(
            paper_manifest.get("startup_time_utc")
            or (paper_session_state or {}).get("started_at_utc")
            or started_at
        )
        ended_at = str((paper_session_state or {}).get("ended_at_utc") or started_at)
    elif wf_manifest:
        started_at = wf_manifest.get("created_at_utc", started_at)
        ended_at = wf_manifest.get("created_at_utc", ended_at)

    symbols = []
    if paper_manifest:
        symbols = paper_manifest.get("symbols", [])
    elif wf_manifest:
        symbols = wf_manifest.get("symbols", [])
    active_symbol = symbols[0] if symbols else "EURUSD"

    regime = "TREND"
    regime_probs = {"TREND": 0.5, "CHOP": 0.3, "RISK_OFF": 0.2}
    if paper_strategy_summary:
        regime = str(paper_strategy_summary.get("last_regime", regime) or regime)
    elif paper_session_state:
        regime = str(paper_session_state.get("last_regime", regime) or regime)

    status = "completed"
    if artifact_context in {"paper_strategy", "paper_scaffold"}:
        session_status = str((paper_session_state or {}).get("status", "stopped") or "stopped")
        if artifact_context == "paper_strategy":
            status = f"paper_{session_status}"
        else:
            status = f"paper_scaffold_{session_status}"
    elif errors:
        status = "completed_with_errors"
    elif warnings:
        status = "completed_with_warnings"

    return {
        "run_id": paper_manifest.get("run_id", wf_run_id) if paper_manifest else wf_run_id,
        "wf_run_id": wf_run_id if wf_manifest else None,
        "started_at": started_at,
        "ended_at": ended_at,
        "symbols": symbols,
        "active_symbol": active_symbol,
        "regime": regime,
        "regime_probabilities": regime_probs,
        "status": status,
        "data_profile": (
            paper_manifest.get("data_source", "unknown")
            if paper_manifest
            else wf_manifest.get("data_profile", "unknown")
            if wf_manifest
            else "unknown"
        ),
        "pipeline_version": (
            str(paper_strategy_summary.get("status", "paper"))
            if paper_strategy_summary
            else "paper_scaffold"
            if paper_manifest
            else wf_manifest.get("pipeline_version", "unknown")
            if wf_manifest
            else "unknown"
        ),
        "artifact_context": artifact_context,
        "paper_trading_active": artifact_context == "paper_strategy",
        "live_broker": paper_manifest.get("live_broker") if paper_manifest else None,
        "live_rail": paper_manifest.get("live_rail") if paper_manifest else None,
        "broker_order_routing": (
            paper_strategy_summary.get("broker_order_routing", "scaffold_only")
            if paper_strategy_summary
            else "scaffold_only"
            if paper_manifest
            else "historical_only"
        ),
        "strategy_status": (
            paper_strategy_summary.get("status")
            if paper_strategy_summary
            else (paper_session_state or {}).get("status")
        ),
        "data_source": (
            paper_strategy_summary.get("data_source")
            if paper_strategy_summary
            else paper_manifest.get("data_source")
            if paper_manifest
            else wf_manifest.get("data_profile")
            if wf_manifest
            else "unknown"
        ),
        "simulated_market_data": bool(
            paper_strategy_summary.get("simulated_market_data", False) if paper_strategy_summary else False
        ),
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
    }


def normalize_trades(split_dir: Path, mode: str = "hybrid") -> list[dict]:
    """Convert split trades.csv to UI Trade[] format."""
    trades_path = split_dir / mode / "trades.csv"
    if not trades_path.exists():
        # Try hybrid, then pairs_only, then trend_only
        for m in ("hybrid", "pairs_only", "trend_only"):
            p = split_dir / m / "trades.csv"
            if p.exists():
                trades_path = p
                break

    rows = read_csv_rows(trades_path)
    result = []
    for i, row in enumerate(rows):
        try:
            side = "long" if float(row.get("entry_weight", 1)) >= 0 else "short"
            exit_time = row.get("exit_timestamp") or None
            result.append({
                "id": f"t{i+1:04d}",
                "time": row.get("entry_timestamp", ""),
                "exit_time": exit_time,
                "symbol": row.get("symbol", ""),
                "engine_source": row.get("engine_source", "trend").replace("_only", ""),
                "side": side,
                "entry": float(row.get("entry_price", 0)),
                "exit": float(row.get("exit_price")) if row.get("exit_price") else None,
                "stop": float(row.get("entry_price", 0)) * 0.995,  # estimated
                "take_profit": float(row.get("entry_price", 0)) * 1.01,  # estimated
                "size": abs(float(row.get("entry_weight", 1))),
                "pnl": float(row.get("pnl", 0)),
                "pnl_pct": float(row.get("pnl", 0)) * 100,
                "close_reason": row.get("close_reason", None),
                "regime_at_entry": row.get("entry_regime", "TREND"),
                "tags": [row.get("engine_source", "trend").replace("_only", "")],
            })
        except (ValueError, KeyError):
            continue
    return result


def normalize_candles(split_dir: Path, symbol: str) -> list[dict]:
    """
    Try to load OHLCV data for the given symbol.
    Falls back to empty list if no bar data found (UI uses mock candles instead).
    """
    # Try parquet via pandas if available
    try:
        import pandas as pd

        for mode in ("hybrid", "pairs_only", "trend_only"):
            signals_path = split_dir / mode / "signals.csv"
            if signals_path.exists():
                df = pd.read_csv(signals_path, parse_dates=["timestamp"])
                # signals.csv has no OHLCV — skip
                if "close" not in df.columns:
                    continue
                sym_df = df[df["symbol"] == symbol].dropna(subset=["close"])
                if not sym_df.empty:
                    candles = []
                    for _, row in sym_df.iterrows():
                        ts = normalize_timestamp_utc_iso(row.get("timestamp"))
                        if not ts:
                            continue
                        close = float(row["close"])
                        candles.append({
                            "time": ts,
                            "open": close,
                            "high": close * 1.002,
                            "low": close * 0.998,
                            "close": close,
                            "volume": 10000,
                        })
                    return candles
    except ImportError:
        pass

    return []


def normalize_equity(split_dir: Path, mode: str = "hybrid") -> list[dict]:
    """Convert equity_curve.csv to UI EquityPoint[] format."""
    eq_path = split_dir / mode / "equity_curve.csv"
    if not eq_path.exists():
        for m in ("hybrid", "pairs_only", "trend_only"):
            p = split_dir / m / "equity_curve.csv"
            if p.exists():
                eq_path = p
                break

    rows = read_csv_rows(eq_path)
    result = []
    for row in rows:
        try:
            result.append({
                "timestamp": row.get("timestamp", ""),
                "equity": float(row.get("equity", 1.0)),
                "regime_label": row.get("regime_label", "TREND"),
            })
        except (ValueError, KeyError):
            continue
    return result


def collect_errors_warnings(
    proof_checks: dict | None,
    robustness_diag: dict | None,
    regime_qa_rows: list[dict],
) -> tuple[list, list, list]:
    errors = []
    warnings = []
    notes = []

    now = datetime.now(UTC).isoformat()

    if proof_checks:
        failed = [k for k, v in proof_checks.items() if v is False]
        for f in failed:
            errors.append({
                "category": "execution",
                "message": f"Proof check failed: {f}",
                "timestamp": now,
            })

    if robustness_diag and isinstance(robustness_diag, dict):
        for k, v in robustness_diag.items():
            if isinstance(v, str) and "fail" in v.lower():
                warnings.append({
                    "category": "execution",
                    "message": f"Robustness: {k} = {v}",
                    "timestamp": now,
                })

    for row in regime_qa_rows:
        if row.get("pass") == "False":
            warnings.append({
                "category": "execution",
                "message": f"Regime QA failed: {row.get('check', 'unknown')} = {row.get('value', '?')}",
                "timestamp": now,
            })

    return errors, warnings, notes


def normalize_regime_posteriors(split_dir: Path, mode: str = "hybrid") -> list[dict]:
    """Convert regime_posteriors.csv to list of {timestamp, regime_label, TREND, CHOP, RISK_OFF}."""
    for m in (mode, "hybrid", "trend_only", "pairs_only"):
        p = split_dir / m / "regime_posteriors.csv"
        if p.exists():
            rows = read_csv_rows(p)
            result = []
            for row in rows:
                try:
                    result.append({
                        "timestamp": row.get("timestamp", ""),
                        "regime_label": row.get("regime_label", "TREND"),
                        "TREND": float(row.get("TREND", 0)),
                        "CHOP": float(row.get("CHOP", 0)),
                        "RISK_OFF": float(row.get("RISK_OFF", 0)),
                    })
                except (ValueError, KeyError):
                    continue
            return result
    return []


def normalize_engine_allocations(split_dir: Path, mode: str = "hybrid") -> list[dict]:
    """Convert engine_allocations.csv to list of {timestamp, pairs_alloc, trend_alloc, regime_label}."""
    for m in (mode, "hybrid"):
        p = split_dir / m / "engine_allocations.csv"
        if p.exists():
            rows = read_csv_rows(p)
            result = []
            for row in rows:
                try:
                    result.append({
                        "timestamp": row.get("timestamp", ""),
                        "pairs_alloc": float(row.get("pairs_alloc", 0)),
                        "trend_alloc": float(row.get("trend_alloc", 0)),
                        "total_alloc": float(row.get("total_alloc", 0)),
                        "regime_label": row.get("regime_label", "TREND"),
                    })
                except (ValueError, KeyError):
                    continue
            return result
    return []


def normalize_signals_sample(split_dir: Path, mode: str = "hybrid", max_rows: int = 200) -> list[dict]:
    """Return first max_rows of signals.csv as dicts."""
    for m in (mode, "hybrid", "trend_only"):
        p = split_dir / m / "signals.csv"
        if p.exists():
            rows = read_csv_rows(p)
            result = []
            for row in rows[:max_rows]:
                try:
                    result.append({
                        "timestamp": row.get("timestamp", ""),
                        "symbol": row.get("symbol", ""),
                        "direction": row.get("direction", "flat"),
                        "size": float(row.get("size", 0)),
                        "engine_source": row.get("engine_source", "trend"),
                        "confidence": float(row.get("confidence", 0)),
                        "regime_label": row.get("regime_label", "TREND"),
                        "trend_p_up": float(row.get("trend_p_up", 0)),
                        "trend_p_down": float(row.get("trend_p_down", 0)),
                    })
                except (ValueError, KeyError):
                    continue
            return result
    return []


def normalize_walkforward_metrics(wf_dir: Path) -> dict:
    """Build walkforward metrics summary from metrics_by_split.csv."""
    splits_rows = read_csv_rows(wf_dir / "metrics_by_split.csv")
    splits_meta = read_csv_rows(wf_dir / "splits.csv")

    by_mode: dict[str, list] = {}
    for row in splits_rows:
        mode = row.get("mode", "hybrid")
        if mode not in by_mode:
            by_mode[mode] = []
        try:
            by_mode[mode].append({
                "split_idx": int(row.get("split_idx", 0)),
                "total_return": float(row.get("total_return", 0)),
                "sharpe": float(row.get("sharpe", 0)),
                "max_drawdown": float(row.get("max_drawdown", 0)),
                "win_rate": float(row.get("win_rate", 0)),
                "trades": int(row.get("trades", 0)),
            })
        except (ValueError, KeyError):
            continue

    return {
        "splits_meta": splits_meta,
        "by_mode": by_mode,
    }


def normalize_pnl_attribution(wf_dir: Path) -> dict:
    """Build PnL attribution from engine×regime, engine, regime CSVs."""
    engine_regime = read_csv_rows(wf_dir / "pnl_attribution_engine_x_regime.csv")
    engine = read_csv_rows(wf_dir / "pnl_attribution_engine.csv")
    regime = read_csv_rows(wf_dir / "pnl_attribution_regime.csv")
    return {
        "engine_x_regime": engine_regime,
        "by_engine": engine,
        "by_regime": regime,
    }


def normalize_robustness(wf_dir: Path) -> dict:
    """Build robustness data from cost_sweep + param_sweep CSVs."""
    cost_sweep = read_csv_rows(wf_dir / "robustness_cost_sweep.csv")
    param_sweep = read_csv_rows(wf_dir / "robustness_param_sweep.csv")
    diagnostics = read_json(wf_dir / "robustness_diagnostics.json")

    # Parse numeric fields in cost_sweep
    parsed_cost = []
    for row in cost_sweep:
        try:
            parsed_cost.append({
                "scenario": row.get("scenario", ""),
                "commission_bps": float(row.get("commission_bps", 0)),
                "slippage_bps": float(row.get("slippage_bps", 0)),
                "total_return": float(row.get("total_return", 0)),
                "sharpe": float(row.get("sharpe", 0)),
                "max_drawdown": float(row.get("max_drawdown", 0)),
                "win_rate": float(row.get("win_rate", 0)),
            })
        except (ValueError, KeyError):
            continue

    parsed_param = []
    for row in param_sweep:
        try:
            entry = {}
            for k, v in row.items():
                try:
                    entry[k] = float(v)
                except (ValueError, TypeError):
                    entry[k] = v
            parsed_param.append(entry)
        except Exception:
            continue

    return {
        "cost_sweep": parsed_cost,
        "param_sweep": parsed_param,
        "diagnostics": diagnostics if isinstance(diagnostics, dict) else {},
    }


def normalize_pairs_diagnostics(wf_dir: Path) -> list[dict]:
    """Build pairs diagnostics from pairs_diagnostics_by_split.csv."""
    rows = read_csv_rows(wf_dir / "pairs_diagnostics_by_split.csv")
    result = []
    for row in rows:
        try:
            result.append({
                "pair_id": row.get("pair_id", ""),
                "state": row.get("state", "WATCH"),
                "trade_count": int(row.get("trade_count", 0)),
                "primary_reason": row.get("primary_reason", ""),
                "latest_pvalue": float(row["latest_pvalue"]) if row.get("latest_pvalue") else None,
                "latest_beta": float(row["latest_beta"]) if row.get("latest_beta") else None,
                "latest_spread_std": float(row["latest_spread_std"]) if row.get("latest_spread_std") else None,
                "latest_z_abs_p95": float(row["latest_z_abs_p95"]) if row.get("latest_z_abs_p95") else None,
                "split_idx": int(row.get("split_idx", 0)),
            })
        except (ValueError, KeyError):
            continue
    return result


def normalize_proof_checks_ui(raw: dict | None) -> dict:
    """Reshape proof_checks.json into UI-friendly format with per-check details."""
    if not raw or not isinstance(raw, dict):
        return {"pass": False, "checks": {}}

    checks_raw = raw.get("checks", {})
    ui_checks = {}
    for name, info in checks_raw.items():
        if isinstance(info, dict):
            ui_checks[name] = {
                "value": info.get("value"),
                "threshold": info.get("threshold"),
                "pass": bool(info.get("pass", False)),
            }
        else:
            ui_checks[name] = {"value": info, "threshold": None, "pass": bool(info)}

    return {
        "pass": bool(raw.get("pass", False)),
        "checks": ui_checks,
        "engine_abs_pnl": raw.get("engine_abs_pnl", {}),
    }


def normalize_latest_artifacts(
    *,
    wf_dir: Path | None,
    paper_dir: Path | None,
    out_dir: Path,
) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if wf_dir and not wf_dir.exists():
        wf_dir = None
    if paper_dir and not paper_dir.exists():
        paper_dir = None

    wf_manifest = read_json(wf_dir / "run_manifest.json") if wf_dir else None
    proof_checks = read_json(wf_dir / "proof_checks.json") if wf_dir else None
    robustness_diag = read_json(wf_dir / "robustness_diagnostics.json") if wf_dir else None
    paper_manifest = read_json(paper_dir / "run_manifest.json") if paper_dir else None
    paper_session_state = read_json(paper_dir / "session_state.json") if paper_dir else None
    paper_strategy_summary = read_json(paper_dir / "paper_strategy_summary.json") if paper_dir else None
    paper_position_plan = read_json_list(paper_dir / "paper_position_plan.json") if paper_dir else []
    paper_ops_direct = read_json_object(paper_dir / "paper_ops.json") if paper_dir else None
    paper_ops = (
        paper_ops_direct
        if isinstance(paper_ops_direct, dict)
        else normalize_paper_ops(
            paper_dir,
            manifest=paper_manifest if isinstance(paper_manifest, dict) else wf_manifest if isinstance(wf_manifest, dict) else None,
            session_state=paper_session_state if isinstance(paper_session_state, dict) else None,
            strategy_summary=paper_strategy_summary if isinstance(paper_strategy_summary, dict) else None,
        )
    )

    errors: list = []
    warnings: list = []
    notes: list[str] = []
    if paper_dir:
        notes.append(f"Paper run: {paper_dir.name}")
        if isinstance(paper_strategy_summary, dict):
            notes.append(
                "Paper strategy artifacts are sourced from the latest paper run. "
                f"Routing mode: {paper_strategy_summary.get('broker_order_routing', 'unknown')}."
            )
            if bool(paper_strategy_summary.get("simulated_market_data", False)):
                notes.append(
                    "Paper data source is lean_history synthetic data. "
                    "Timestamps are current, but market prices are simulated."
                )
        else:
            notes.append("Paper session is bootstrapped, but no strategy-cycle artifacts have been emitted yet.")
    else:
        regime_qa_rows = read_csv_rows(wf_dir / "regime_qa_by_split.csv") if wf_dir else []
        errors, warnings, notes = collect_errors_warnings(
            proof_checks if isinstance(proof_checks, dict) else None,
            robustness_diag if isinstance(robustness_diag, dict) else None,
            regime_qa_rows,
        )
        notes.append("No paper run detected. State pages are showing historical walk-forward artifacts.")

    if wf_dir:
        notes.append(
            f"Walk-forward run: {wf_dir.name}. "
            f"Splits: {wf_manifest.get('split_params', {}).get('generated_splits', '?') if isinstance(wf_manifest, dict) else '?'}"
        )
        if paper_dir:
            notes.append("Walkforward analytics remain sourced from the latest proof run.")

    resolved_base_run = paper_dir.name if paper_dir else wf_dir.name if wf_dir else "unknown"
    wf_run_id = resolved_base_run + "_ui_" + datetime.now().strftime("%H%M%S")
    manifest = normalize_manifest(
        wf_manifest if isinstance(wf_manifest, dict) else None,
        paper_manifest if isinstance(paper_manifest, dict) else None,
        paper_session_state if isinstance(paper_session_state, dict) else None,
        paper_strategy_summary if isinstance(paper_strategy_summary, dict) else None,
        wf_run_id,
        errors,
        warnings,
        notes,
    )

    split_dir = None
    if wf_dir:
        split_dir = wf_dir / "split_000"
        if not split_dir.exists():
            splits = sorted(wf_dir.glob("split_*"))
            split_dir = splits[0] if splits else None

    symbols = manifest.get("symbols", ["EURUSD"])
    active_symbol = manifest.get("active_symbol", symbols[0] if symbols else "EURUSD")

    if paper_dir:
        trades = normalize_paper_trades(paper_dir)
        candles = normalize_paper_candles(paper_dir, active_symbol)
        equity_curve, paper_equity_df = normalize_paper_equity(paper_dir)
        paper_ops_summary = read_json(paper_dir / "ops_summary.json")
        manifest["metrics"] = _paper_metrics(
            trades,
            paper_equity_df,
            paper_ops_summary if isinstance(paper_ops_summary, dict) else None,
        )
    else:
        trades = normalize_trades(split_dir) if split_dir else []
        candles = normalize_candles(split_dir, active_symbol) if split_dir else []
        equity_curve = normalize_equity(split_dir) if split_dir else []
        if wf_dir:
            summary = read_json(wf_dir / "phase5_report_summary.json")
            if isinstance(summary, dict):
                manifest["metrics"] = {
                    "sharpe_ratio": float(summary.get("sharpe_ratio", 0) or 0),
                    "total_return": float(summary.get("total_return", 0) or 0),
                    "max_drawdown": float(summary.get("max_drawdown", 0) or 0),
                    "win_rate": float(summary.get("win_rate", 0) or 0),
                    "num_trades": int(summary.get("num_trades", 0) or 0),
                    "avg_trade_pnl": float(summary.get("avg_trade_pnl", 0) or 0),
                }

    events = normalize_paper_events(paper_dir)

    regime_posteriors: list[dict] = []
    engine_allocations: list[dict] = []
    signals_sample: list[dict] = []
    pair_history: dict[str, object] = {}
    trend_model_meta: dict | None = None
    trend_decisions: list[dict] = []
    indicator_snapshots: list[dict] = []
    broker_context_latest: dict | None = None
    walkforward_metrics: dict = {}
    pnl_attribution: dict = {}
    robustness: dict = {}
    pairs_diagnostics: list[dict] = []
    proof_checks_ui: dict = {}
    promotion_decision: dict | None = None

    if paper_dir:
        regime_posteriors = read_json_list(paper_dir / "regime_posteriors.json")
        engine_allocations = read_json_list(paper_dir / "engine_allocations.json")
        signals_sample = read_json_list(paper_dir / "signals_sample.json")
        pairs_diagnostics = read_json_list(paper_dir / "pairs_diagnostics.json")
        pair_history = read_json_object(paper_dir / "pair_history.json") or {}
        trend_model_meta = read_json_object(paper_dir / "trend_model_meta.json")
        trend_decisions = read_json_list(paper_dir / "trend_decisions.json")
        indicator_snapshots = read_json_list(paper_dir / "indicator_snapshots.json")
        broker_context_latest = read_json_object(paper_dir / "broker_context_latest.json")

    if split_dir:
        if not regime_posteriors:
            regime_posteriors = normalize_regime_posteriors(split_dir)
        if not engine_allocations:
            engine_allocations = normalize_engine_allocations(split_dir)
        if not signals_sample:
            signals_sample = normalize_signals_sample(split_dir)

    if wf_dir:
        walkforward_metrics = normalize_walkforward_metrics(wf_dir)
        pnl_attribution = normalize_pnl_attribution(wf_dir)
        robustness = normalize_robustness(wf_dir)
        if not pairs_diagnostics:
            pairs_diagnostics = normalize_pairs_diagnostics(wf_dir)
        raw_proof = read_json(wf_dir / "proof_checks.json")
        proof_checks_ui = normalize_proof_checks_ui(raw_proof if isinstance(raw_proof, dict) else None)
        raw_promo = read_json(wf_dir / "promotion_decision.json")
        promotion_decision = raw_promo if isinstance(raw_promo, dict) else None

    write_json(out_dir / "manifest.json", manifest)
    write_json(out_dir / "trades.json", trades)
    write_json(out_dir / "candles.json", candles)
    write_json(out_dir / "equity_curve.json", equity_curve)
    write_json(out_dir / "events.json", events)
    write_json(out_dir / "paper_ops.json", paper_ops)
    write_json(out_dir / "paper_strategy_summary.json", paper_strategy_summary)
    write_json(out_dir / "paper_position_plan.json", paper_position_plan)
    write_json(out_dir / "regime_posteriors.json", regime_posteriors)
    write_json(out_dir / "engine_allocations.json", engine_allocations)
    write_json(out_dir / "signals_sample.json", signals_sample)
    write_json(out_dir / "pair_history.json", pair_history)
    write_json(out_dir / "trend_model_meta.json", trend_model_meta)
    write_json(out_dir / "trend_decisions.json", trend_decisions)
    write_json(out_dir / "indicator_snapshots.json", indicator_snapshots)
    write_json(out_dir / "broker_context_latest.json", broker_context_latest)
    write_json(out_dir / "walkforward_metrics.json", walkforward_metrics)
    write_json(out_dir / "pnl_attribution.json", pnl_attribution)
    write_json(out_dir / "robustness.json", robustness)
    write_json(out_dir / "pairs_diagnostics.json", pairs_diagnostics)
    write_json(out_dir / "proof_checks.json", proof_checks_ui)
    if promotion_decision:
        write_json(out_dir / "promotion_decision.json", promotion_decision)

    return {
        "manifest": manifest,
        "trades": trades,
        "candles": candles,
        "equity_curve": equity_curve,
        "events": events,
        "paper_ops": paper_ops,
        "paper_strategy_summary": paper_strategy_summary,
        "paper_position_plan": paper_position_plan,
        "regime_posteriors": regime_posteriors,
        "engine_allocations": engine_allocations,
        "signals_sample": signals_sample,
        "pair_history": pair_history,
        "trend_model_meta": trend_model_meta,
        "trend_decisions": trend_decisions,
        "indicator_snapshots": indicator_snapshots,
        "broker_context_latest": broker_context_latest,
        "walkforward_metrics": walkforward_metrics,
        "pnl_attribution": pnl_attribution,
        "robustness": robustness,
        "pairs_diagnostics": pairs_diagnostics,
        "proof_checks": proof_checks_ui,
        "promotion_decision": promotion_decision,
    }


def main():
    parser = argparse.ArgumentParser(description="Normalize algo artifacts for UI")
    parser.add_argument("--wf-run-id", default=None, help="Walk-forward run ID")
    parser.add_argument("--paper-run-dir", default=None, help="Paper run directory")
    parser.add_argument("--out-dir", default=None, help="Output directory for normalized artifacts")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent
    artifacts_root = repo_root / "artifacts"
    wf_root = artifacts_root / "walkforward"
    outputs_paper = repo_root / "outputs" / "paper"
    if args.out_dir:
        out_dir = Path(args.out_dir)
        if not out_dir.is_absolute():
            out_dir = repo_root / out_dir
    else:
        out_dir = artifacts_root / "latest_run"

    wf_dir = wf_root / args.wf_run_id if args.wf_run_id else find_latest_dir(wf_root)
    if not wf_dir or not wf_dir.exists():
        print(f"[normalize] No walkforward run found in {wf_root}", file=sys.stderr)
        wf_dir = None

    if args.paper_run_dir:
        paper_dir = Path(args.paper_run_dir)
    else:
        paper_dir = find_latest_paper_run(outputs_paper)

    print(f"[normalize] WF run dir:    {wf_dir}")
    print(f"[normalize] Paper run dir: {paper_dir}")
    print(f"[normalize] Output dir:    {out_dir}")

    payload = normalize_latest_artifacts(wf_dir=wf_dir, paper_dir=paper_dir, out_dir=out_dir)
    print(f"[normalize] Wrote manifest.json ({len(payload['manifest'].get('errors', []))} errors, {len(payload['manifest'].get('warnings', []))} warnings)")
    print(f"[normalize] Wrote trades.json ({len(payload['trades'])} trades)")
    print(f"[normalize] Wrote candles.json ({len(payload['candles'])} bars)")
    print(f"[normalize] Wrote equity_curve.json ({len(payload['equity_curve'])} points)")
    print(f"[normalize] Wrote events.json ({len(payload['events'])} rows)")
    print(f"[normalize] Wrote paper_ops.json (status={payload['paper_ops'].get('objectstore_status')})")
    print(
        f"[normalize] Wrote paper_strategy_summary.json ({'present' if payload['paper_strategy_summary'] else 'missing'})"
    )
    print(
        f"[normalize] Wrote paper_position_plan.json ({len(payload['paper_position_plan'])} rows)"
    )
    print(f"[normalize] Wrote regime_posteriors.json ({len(payload['regime_posteriors'])} rows)")
    print(f"[normalize] Wrote engine_allocations.json ({len(payload['engine_allocations'])} rows)")
    print(f"[normalize] Wrote signals_sample.json ({len(payload['signals_sample'])} rows)")
    print(f"[normalize] Wrote pair_history.json ({len(payload['pair_history'])} pairs)")
    print(f"[normalize] Wrote trend_model_meta.json ({'present' if payload['trend_model_meta'] else 'missing'})")
    print(f"[normalize] Wrote trend_decisions.json ({len(payload['trend_decisions'])} rows)")
    print(
        f"[normalize] Wrote indicator_snapshots.json ({len(payload['indicator_snapshots'])} rows)"
    )
    print(
        "[normalize] Wrote broker_context_latest.json "
        f"({'present' if payload['broker_context_latest'] else 'missing'})"
    )
    print("[normalize] Wrote walkforward_metrics.json")
    print("[normalize] Wrote pnl_attribution.json")
    print(f"[normalize] Wrote robustness.json ({len(payload['robustness'].get('cost_sweep', []))} cost scenarios)")
    print(f"[normalize] Wrote pairs_diagnostics.json ({len(payload['pairs_diagnostics'])} pairs)")
    print(f"[normalize] Wrote proof_checks.json (pass={payload['proof_checks'].get('pass')})")
    if payload["promotion_decision"]:
        print(f"[normalize] Wrote promotion_decision.json (pass={payload['promotion_decision'].get('pass')})")
    print(f"[normalize] Done. Artifacts written to {out_dir}")


if __name__ == "__main__":
    main()
