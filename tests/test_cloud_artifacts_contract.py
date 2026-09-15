"""Artifact contract validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from fx_lean_engine.backtest.validation import validate_backtest_artifacts


REQUIRED_TABLES = ["signals.csv", "orders.csv", "equity_curve.csv", "regime.csv", "features.csv", "targets.csv"]
PHASE2_TABLES = ["pairs_candidates.csv", "pairs_scan.csv", "pair_state_events.csv", "pnl_by_pair.csv"]


def _write_minimal_artifacts(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_TABLES:
        pd.DataFrame([{"x": 1.0}]).to_csv(run_dir / name, index=False)

    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "run_id": "abc",
                "symbols": ["EURUSD"],
                "resolution": "Minute",
                "bar_interval_minutes": 15,
                "start": "2025-01-01",
                "end": "2025-01-29",
                "signals_count": 1,
                "orders_count": 1,
                "trades_count": 1,
                "max_gross_exposure": 0.1,
                "avg_holding_bars": 4.0,
                "turnover": 0.2,
                "warnings_count": 0,
                "errors_count": 0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "abc",
                "generated_at": "2025-01-01T00:00:00+00:00",
                "git_sha": "deadbeef",
                "runtime_mode": "backtest",
                "data_source": "cloud",
                "config_hashes": {"runtime": "123"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "config_snapshot.yaml").write_text(
        yaml.safe_dump({"runtime": {"execution_mode": "backtest"}}, sort_keys=False),
        encoding="utf-8",
    )


def _write_phase2_artifacts(run_dir: Path) -> None:
    for name in PHASE2_TABLES:
        pd.DataFrame([{"x": 1.0}]).to_csv(run_dir / name, index=False)
    (run_dir / "phase2_demo_report.md").write_text("# report\n", encoding="utf-8")


def test_validate_backtest_artifacts_happy_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_minimal_artifacts(run_dir)
    ok, issues = validate_backtest_artifacts(run_dir)
    assert ok is True
    assert issues == []


def test_validate_backtest_artifacts_missing_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_minimal_artifacts(run_dir)
    (run_dir / "targets.csv").unlink()
    ok, issues = validate_backtest_artifacts(run_dir)
    assert ok is False
    assert any("missing artifact: targets.csv" in issue for issue in issues)


def test_validate_backtest_artifacts_require_phase2(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_minimal_artifacts(run_dir)

    ok, issues = validate_backtest_artifacts(run_dir, require_phase2=True)
    assert ok is False
    assert any("missing artifact: pairs_scan.csv" in issue for issue in issues)

    _write_phase2_artifacts(run_dir)
    ok, issues = validate_backtest_artifacts(run_dir, require_phase2=True)
    assert ok is True
    assert issues == []
