"""Unit tests for run artifact contract validation."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from fx_hybrid_engine.evaluation.contract import validate_run_tree, validate_split_mode_run


def _write_required_files(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"timestamp": "2024-01-01T00:00:00+00:00", "symbol": "EURUSD", "direction": "long", "size": 0.1, "engine_source": "trend", "mode": "hybrid"},
        ]
    ).to_csv(run_dir / "signals.csv", index=False)
    pd.DataFrame(
        [
            {
                "entry_timestamp": "2024-01-01T00:00:00+00:00",
                "exit_timestamp": "2024-01-02T00:00:00+00:00",
                "symbol": "EURUSD",
                "engine_source": "trend",
                "entry_regime": "TREND",
                "exit_regime": "TREND",
                "pnl": 0.01,
                "mode": "hybrid",
            }
        ]
    ).to_csv(run_dir / "trades.csv", index=False)
    pd.DataFrame(
        [
            {"timestamp": "2024-01-01T00:00:00+00:00", "symbol": "EURUSD", "delta_weight": 0.1, "price": 1.1, "engine_source": "trend", "regime_label": "TREND", "mode": "hybrid"},
        ]
    ).to_csv(run_dir / "fills.csv", index=False)
    pd.DataFrame(
        [
            {"timestamp": "2024-01-01T00:00:00+00:00", "equity": 1.0, "net_return": 0.0, "gross_return": 0.0, "turnover": 0.1, "costs": 0.0, "mode": "hybrid"},
        ]
    ).to_csv(run_dir / "equity_curve.csv", index=False)
    pd.DataFrame(
        [
            {"timestamp": "2024-01-01T00:00:00+00:00", "pairs_alloc": 0.0, "trend_alloc": 0.1, "total_alloc": 0.1, "regime_label": "TREND", "mode": "hybrid"},
        ]
    ).to_csv(run_dir / "engine_allocations.csv", index=False)
    pd.DataFrame(
        [
            {"timestamp": "2024-01-01T00:00:00+00:00", "regime_label": "TREND", "TREND": 0.9, "CHOP": 0.1, "RISK_OFF": 0.0, "mode": "hybrid"},
        ]
    ).to_csv(run_dir / "regime_posteriors.csv", index=False)
    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump({"total_return": 0.01, "sharpe": 1.0, "max_drawdown": 0.02, "trades": 1}, f)
    with open(run_dir / "config_snapshot.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump({"ok": True}, f)


def _write_manifest(root: Path) -> None:
    with open(root / "run_manifest.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "wf_run_id": "unit_test",
                "created_at_utc": "2026-02-27T00:00:00+00:00",
                "config_path": str(root / "cfg.yaml"),
                "git_commit": "unknown",
                "config_hash": "b" * 64,
                "schema_version": "1.0.0",
                "seed": 42,
                "precompute_enabled": True,
                "mode_reuse_enabled": True,
                "skip_robustness": True,
                "data_profile": "local_smoke",
                "symbols": ["EURUSD"],
                "pair_list": [["EURUSD", "GBPUSD"]],
                "trend_symbols": ["EURUSD"],
                "split_params": {
                    "train_window_days": 10,
                    "test_window_days": 5,
                    "step_days": 5,
                    "max_splits": 1,
                    "generated_splits": 1,
                },
                "cost_params": {"commission_bps": 1.0, "slippage_bps": 1.0},
                "cache_fingerprint": "a" * 64,
                "pipeline_version": "phase5.1",
            },
            f,
        )


def _write_root_tables(root: Path) -> None:
    pd.DataFrame(
        [
            {
                "split_idx": 0,
                "mode": "hybrid",
                "total_return": 0.01,
                "sharpe": 1.0,
                "max_drawdown": 0.02,
                "trades": 1,
                "precompute_enabled": True,
                "mode_reuse_enabled": True,
                "cache_fingerprint": "a" * 64,
                "pipeline_version": "phase5.1",
            }
        ]
    ).to_csv(root / "metrics_by_split.csv", index=False)
    pd.DataFrame([{"split_idx": 0}]).to_csv(root / "splits.csv", index=False)
    pd.DataFrame([{"engine_source": "trend", "n_trades": 1, "total_pnl": 0.01, "win_rate": 1.0, "pnl_share": 1.0}]).to_csv(
        root / "pnl_attribution_engine.csv",
        index=False,
    )
    pd.DataFrame([{"entry_regime": "TREND", "n_trades": 1, "total_pnl": 0.01, "win_rate": 1.0, "pnl_share": 1.0}]).to_csv(
        root / "pnl_attribution_regime.csv",
        index=False,
    )
    pd.DataFrame(
        [
            {
                "engine_source": "trend",
                "entry_regime": "TREND",
                "n_trades": 1,
                "total_pnl": 0.01,
                "win_rate": 1.0,
                "pnl_share_within_engine": 1.0,
            }
        ]
    ).to_csv(root / "pnl_attribution_engine_x_regime.csv", index=False)


def _write_split_root(split_root: Path) -> None:
    split_root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"pair_id": "EURUSD-GBPUSD"}]).to_csv(split_root / "pairs_candidates.csv", index=False)
    pd.DataFrame([{"pair_id": "EURUSD-GBPUSD", "scan_idx": 0, "timestamp": "2024-01-01T00:00:00+00:00"}]).to_csv(
        split_root / "pairs_scan.csv",
        index=False,
    )
    pd.DataFrame([{"pair_id": "EURUSD-GBPUSD", "reason": "tradable"}]).to_csv(split_root / "pairs_diagnostics.csv", index=False)
    pd.DataFrame(
        [
            {
                "timestamp": "2024-01-01T00:00:00+00:00",
                "pair_id": "EURUSD-GBPUSD",
                "from_state": "WATCH",
                "to_state": "TRADABLE",
                "reason": "p_enter_pass",
                "disabled_until_scan": "",
            }
        ]
    ).to_csv(split_root / "pair_state_events.csv", index=False)
    (split_root / "pair_state_snapshot.json").write_text(json.dumps({"EURUSD-GBPUSD": {"state": "TRADABLE"}}), encoding="utf-8")
    pd.DataFrame([{"timestamp": "2024-01-01T00:00:00+00:00", "regime_label": "TREND"}]).to_csv(
        split_root / "regime_events.csv",
        index=False,
    )
    (split_root / "regime_summary.json").write_text(json.dumps({"pass": True}), encoding="utf-8")
    (split_root / "hmm_state_map.json").write_text(json.dumps({"state_map": {0: "TREND"}}), encoding="utf-8")


def test_contract_validator_passes_for_valid_run(tmp_path):
    run_dir = tmp_path / "split_000" / "hybrid"
    _write_required_files(run_dir)
    issues = validate_split_mode_run(run_dir)
    assert not [i for i in issues if i.level == "error"]


def test_contract_validator_fails_for_missing_artifact(tmp_path):
    run_dir = tmp_path / "split_000" / "hybrid"
    _write_required_files(run_dir)
    (run_dir / "metrics.json").unlink()
    issues = validate_split_mode_run(run_dir)
    assert any("Missing required artifact" in i.message for i in issues)


def test_run_tree_validator_fails_when_manifest_missing(tmp_path):
    run_dir = tmp_path / "split_000" / "hybrid"
    _write_required_files(run_dir)
    _write_split_root(tmp_path / "split_000")
    _write_root_tables(tmp_path)
    ok, issues = validate_run_tree(tmp_path)
    assert not ok
    assert any("run_manifest.json" in i.message for i in issues)


def test_run_tree_validator_passes_with_manifest(tmp_path):
    run_dir = tmp_path / "split_000" / "hybrid"
    _write_required_files(run_dir)
    _write_split_root(tmp_path / "split_000")
    _write_root_tables(tmp_path)
    _write_manifest(tmp_path)
    ok, issues = validate_run_tree(tmp_path)
    assert ok, "\n".join(i.message for i in issues)


def test_run_tree_validator_fails_on_metrics_nan(tmp_path):
    run_dir = tmp_path / "split_000" / "hybrid"
    _write_required_files(run_dir)
    _write_split_root(tmp_path / "split_000")
    _write_root_tables(tmp_path)
    _write_manifest(tmp_path)
    metrics = pd.read_csv(tmp_path / "metrics_by_split.csv")
    metrics.loc[0, "sharpe"] = None
    metrics.to_csv(tmp_path / "metrics_by_split.csv", index=False)
    ok, issues = validate_run_tree(tmp_path)
    assert not ok
    assert any("metrics_by_split has NaNs in 'sharpe'" in i.message for i in issues)
