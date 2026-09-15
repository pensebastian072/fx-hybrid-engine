from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.normalize_artifacts import find_latest_paper_run, normalize_latest_artifacts


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_normalize_latest_artifacts_prefers_paper_run_over_historical_walkforward(tmp_path):
    wf_dir = tmp_path / "wf_run"
    split_dir = wf_dir / "split_000" / "hybrid"
    split_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        wf_dir / "run_manifest.json",
        {
            "created_at_utc": "2026-03-08T00:00:00+00:00",
            "symbols": ["EURUSD"],
            "data_profile": "local_smoke",
            "pipeline_version": "phase5.1",
            "split_params": {"generated_splits": 1},
        },
    )
    _write_json(wf_dir / "phase5_report_summary.json", {"total_return": 0.1, "num_trades": 5})
    _write_json(wf_dir / "proof_checks.json", {"pass": False, "checks": {"edge": False}})
    (split_dir / "trades.csv").write_text(
        "entry_timestamp,exit_timestamp,symbol,engine_source,entry_price,exit_price,entry_weight,pnl,close_reason,entry_regime\n"
        "2019-01-01T00:00:00Z,2019-01-02T00:00:00Z,GBPUSD,trend,1.0,1.1,1.0,0.1,signal_flip_or_flat,TREND\n",
        encoding="utf-8",
    )
    (split_dir / "equity_curve.csv").write_text(
        "timestamp,equity,regime_label\n2019-01-01T00:00:00Z,1.0,TREND\n",
        encoding="utf-8",
    )

    paper_dir = tmp_path / "paper_run"
    paper_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        paper_dir / "run_manifest.json",
        {
            "run_id": "paper_001",
            "startup_time_utc": "2026-03-09T00:00:00+00:00",
            "git_commit": "abc123",
            "config_hash": "sha256:test",
            "schema_version": "1.0.0",
            "seed": 42,
            "data_source": "lean_history",
            "live_broker": "tastytrade",
            "live_rail": "tastytrade_paper",
            "symbols": ["EURUSD"],
            "runtime_toggles": {},
        },
    )
    _write_json(
        paper_dir / "session_state.json",
        {
            "status": "running",
            "started_at_utc": "2026-03-09T00:00:00+00:00",
            "last_regime": "TREND",
        },
    )
    _write_json(
        paper_dir / "paper_strategy_summary.json",
        {
            "status": "completed",
            "broker_order_routing": "local_paper_only",
            "data_source": "lean_history",
            "simulated_market_data": True,
            "last_regime": "TREND",
        },
    )
    _write_json(
        paper_dir / "pairs_diagnostics.json",
        [
            {
                "pair_id": "EURUSD_GBPUSD",
                "state": "TRADABLE",
                "trade_count": 1,
                "primary_reason": "paper_cycle",
                "latest_pvalue": 0.03,
                "latest_beta": 1.1,
                "latest_spread_std": 0.002,
                "latest_z_abs_p95": 2.4,
                "split_idx": 0,
            }
        ],
    )
    _write_json(
        paper_dir / "pair_history.json",
        {
            "EURUSD_GBPUSD": {
                "scan_history": [
                    {
                        "date": "2026-03-09",
                        "pvalue": 0.03,
                        "beta": 1.1,
                        "spread_std": 0.002,
                        "z_abs_p95": 2.4,
                        "state": "TRADABLE",
                    }
                ],
                "zscore_series": [{"date": "2026-03-09T00:15:00Z", "zscore": 2.1}],
                "state_events": [
                    {
                        "date": "2026-03-09T00:15:00Z",
                        "event": "pair_enabled",
                        "reason": "scan_passed",
                    }
                ],
            }
        },
    )
    _write_json(
        paper_dir / "signals_sample.json",
        [
            {
                "timestamp": "2026-03-09T00:15:00+00:00",
                "symbol": "EURUSD",
                "direction": "long",
                "size": 0.1,
                "engine_source": "trend",
                "confidence": 0.81,
                "regime_label": "TREND",
                "trend_p_up": 0.81,
                "trend_p_down": 0.19,
            }
        ],
    )
    _write_json(
        paper_dir / "trend_model_meta.json",
        {
            "model_version": "in_memory",
            "training_window_days": 5,
            "feature_schema_hash": "abc123",
            "last_retrain_time": "2026-03-09T00:00:00+00:00",
            "calibration_score": None,
            "feature_columns": ["mom_5", "vol_20"],
            "label_mode": "binary",
            "label_horizon_bars": 8,
            "label_threshold_bps": 6.0,
        },
    )
    _write_json(
        paper_dir / "trend_decisions.json",
        [
            {
                "timestamp": "2026-03-09T00:15:00+00:00",
                "symbol": "EURUSD",
                "direction": "long",
                "confidence": 0.81,
                "regime_label": "TREND",
                "trend_p_up": 0.81,
                "trend_p_down": 0.19,
                "decision_threshold": 0.65,
                "decision_reason": "threshold_long",
                "trend_model_version": "in_memory",
                "rsi": 58.4,
                "realized_vol": 0.12,
                "sma_crossover": 0.004,
                "macd_line": 0.0011,
                "macd_signal": 0.0009,
                "macd_histogram": 0.0002,
                "observed_divergence": "none",
            }
        ],
    )
    _write_json(
        paper_dir / "indicator_snapshots.json",
        [
            {
                "timestamp": "2026-03-09T00:15:00+00:00",
                "symbol": "EURUSD",
                "close": 1.0805,
                "sma_fast": 1.0799,
                "sma_slow": 1.0782,
                "rsi": 58.4,
                "realized_vol": 0.12,
                "momentum_slope": 0.002,
                "sma_crossover": 0.004,
                "macd_line": 0.0011,
                "macd_signal": 0.0009,
                "macd_histogram": 0.0002,
                "macd_bullish_divergence": False,
                "macd_bearish_divergence": False,
            }
        ],
    )
    _write_json(
        paper_dir / "broker_context_latest.json",
        {
            "provider": "tastytrade",
            "available": False,
            "connection_status": "broker_context_unavailable",
            "account_number": None,
            "symbol_map_ready_count": 0,
            "symbol_map_missing": ["EURUSD"],
            "positions_count": 0,
            "open_orders_count": 0,
            "error": "Missing tastytrade credentials in environment.",
        },
    )
    _write_json(
        paper_dir / "paper_position_plan.json",
        [
            {
                "symbol": "EURUSD",
                "broker_symbol": "",
                "target_weight": 0.1,
                "direction": "long",
                "orderable_contract_ready": False,
            }
        ],
    )
    _write_json(
        paper_dir / "paper_ops.json",
        {
            "run_manifest": {
                "run_id": "paper_001",
                "git_commit": "abc123",
                "config_hash": "sha256:test",
                "schema_version": "1.0.0",
                "created_at_utc": "2026-03-09T00:00:00+00:00",
                "seed": 42,
                "precompute_enabled": False,
                "mode_reuse_enabled": False,
                "data_profile": "lean_history",
                "pipeline_version": "completed",
                "live_broker": "tastytrade",
                "live_rail": "tastytrade_paper",
                "broker_order_routing": "local_paper_only",
                "strategy_status": "completed",
                "data_source": "lean_history",
                "simulated_market_data": True,
            },
            "stale_data_count": 1,
            "missing_bars_count": 0,
            "orders_per_hour": 1.0,
            "reject_rate": 0.0,
            "last_bars": [
                {"timestamp": "2026-03-09T00:15:00+00:00", "symbol": "EURUSD", "close": 1.0805}
            ],
            "objectstore_status": "stopped",
            "broker_context": {
                "provider": "tastytrade",
                "available": False,
                "connection_status": "broker_context_unavailable",
                "account_number": None,
            },
            "strategy_summary": {
                "status": "completed",
                "signals_emitted": 1,
                "fills_emitted": 1,
                "closed_trades": 1,
            },
            "no_trade_summary": {
                "signals_emitted": 1,
                "fills_emitted": 1,
                "closed_trades": 1,
                "observed_pair_count": 1,
                "tradable_pair_count": 1,
            },
        },
    )
    _write_json(
        paper_dir / "paper_trades.json",
        [
            {
                "id": "paper_0001",
                "time": "2026-03-09T00:15:00+00:00",
                "exit_time": None,
                "symbol": "EURUSD",
                "engine_source": "trend",
                "side": "long",
                "entry": 1.08,
                "exit": None,
                "stop": 1.07,
                "take_profit": 1.09,
                "size": 0.1,
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "close_reason": None,
                "regime_at_entry": "TREND",
                "tags": ["trend"],
            }
        ],
    )
    pd.DataFrame(
        [
            {
                "timestamp": "2026-03-09 00:15:00+00:00",
                "symbol": "EURUSD",
                "open": 1.08,
                "high": 1.081,
                "low": 1.079,
                "close": 1.0805,
                "volume": 1000,
            }
        ]
    ).to_parquet(paper_dir / "bars.parquet", index=False)
    pd.DataFrame(
        [
            {"timestamp": "2026-03-09T00:15:00+00:00", "equity": 1.0, "regime_label": "TREND"},
            {"timestamp": "2026-03-09T00:30:00+00:00", "equity": 1.01, "regime_label": "TREND"},
        ]
    ).to_parquet(paper_dir / "equity_curve.parquet", index=False)
    pd.DataFrame(
        [{"timestamp": "2026-03-09T00:15:00+00:00", "symbol": "EURUSD", "order_type": "paper_buy"}]
    ).to_parquet(paper_dir / "orders.parquet", index=False)
    pd.DataFrame(
        [{"timestamp": "2026-03-09T00:15:00+00:00", "reason": "paper_strategy_cycle_complete"}]
    ).to_parquet(paper_dir / "risk_events.parquet", index=False)
    (paper_dir / "broker_events.jsonl").write_text(
        '{"timestamp":"2026-03-09T00:15:00+00:00","event":"strategy_cycle_complete"}\n',
        encoding="utf-8",
    )

    out_dir = tmp_path / "latest_run"
    normalize_latest_artifacts(wf_dir=wf_dir, paper_dir=paper_dir, out_dir=out_dir)

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    trades = json.loads((out_dir / "trades.json").read_text(encoding="utf-8"))
    candles = json.loads((out_dir / "candles.json").read_text(encoding="utf-8"))
    paper_ops = json.loads((out_dir / "paper_ops.json").read_text(encoding="utf-8"))
    pair_history = json.loads((out_dir / "pair_history.json").read_text(encoding="utf-8"))
    trend_model_meta = json.loads((out_dir / "trend_model_meta.json").read_text(encoding="utf-8"))
    trend_decisions = json.loads((out_dir / "trend_decisions.json").read_text(encoding="utf-8"))
    indicator_snapshots = json.loads((out_dir / "indicator_snapshots.json").read_text(encoding="utf-8"))
    broker_context = json.loads((out_dir / "broker_context_latest.json").read_text(encoding="utf-8"))
    position_plan = json.loads((out_dir / "paper_position_plan.json").read_text(encoding="utf-8"))
    strategy_summary = json.loads((out_dir / "paper_strategy_summary.json").read_text(encoding="utf-8"))

    assert manifest["artifact_context"] == "paper_strategy"
    assert manifest["status"] == "paper_running"
    assert manifest["broker_order_routing"] == "local_paper_only"
    assert manifest["simulated_market_data"] is True
    assert any("simulated" in note.lower() for note in manifest["notes"])
    assert trades[0]["id"] == "paper_0001"
    assert trades[0]["symbol"] == "EURUSD"
    assert candles
    for candle in candles:
        assert "T" in candle["time"]
        parsed = pd.Timestamp(candle["time"])
        assert not pd.isna(parsed)
        assert parsed.tzinfo is not None
    assert paper_ops["run_manifest"]["live_broker"] == "tastytrade"
    assert paper_ops["run_manifest"]["broker_order_routing"] == "local_paper_only"
    assert "EURUSD_GBPUSD" in pair_history
    assert trend_model_meta["model_version"] == "in_memory"
    assert trend_decisions[0]["decision_reason"] == "threshold_long"
    assert indicator_snapshots[0]["macd_histogram"] == 0.0002
    assert broker_context["connection_status"] == "broker_context_unavailable"
    assert position_plan[0]["symbol"] == "EURUSD"
    assert strategy_summary["status"] == "completed"


def test_find_latest_paper_run_prefers_completed_strategy_over_newer_scaffold(tmp_path):
    outputs_paper = tmp_path / "outputs" / "paper"
    strategy_run = outputs_paper / "2026-03-09" / "paper_strategy"
    scaffold_run = outputs_paper / "2026-03-10" / "paper_scaffold"
    strategy_run.mkdir(parents=True, exist_ok=True)
    scaffold_run.mkdir(parents=True, exist_ok=True)
    _write_json(strategy_run / "paper_strategy_summary.json", {"status": "completed"})
    _write_json(scaffold_run / "session_state.json", {"status": "running"})

    selected = find_latest_paper_run(outputs_paper)

    assert selected == strategy_run


def test_normalize_latest_artifacts_without_walkforward_emits_empty_walkforward_metrics(tmp_path):
    paper_dir = tmp_path / "paper_only_run"
    paper_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        paper_dir / "run_manifest.json",
        {
            "run_id": "paper_only_001",
            "startup_time_utc": "2026-03-10T00:00:00+00:00",
            "symbols": ["EURUSD"],
            "data_source": "lean_history",
        },
    )
    _write_json(
        paper_dir / "session_state.json",
        {
            "status": "stopped",
            "started_at_utc": "2026-03-10T00:00:00+00:00",
            "ended_at_utc": "2026-03-10T00:10:00+00:00",
        },
    )
    _write_json(
        paper_dir / "paper_strategy_summary.json",
        {
            "status": "completed",
            "broker_order_routing": "local_paper_only",
            "data_source": "lean_history",
        },
    )
    _write_json(paper_dir / "paper_trades.json", [])

    out_dir = tmp_path / "custom_run_history"
    payload = normalize_latest_artifacts(wf_dir=None, paper_dir=paper_dir, out_dir=out_dir)

    assert payload["walkforward_metrics"] == {}
    walkforward_metrics = json.loads((out_dir / "walkforward_metrics.json").read_text(encoding="utf-8"))
    assert walkforward_metrics == {}
