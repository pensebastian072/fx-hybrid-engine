"""Phase 2 metrics and artifact presence tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import yaml

from fx_lean_engine.backtest.synthetic import run_synthetic_backtest
from fx_lean_engine.backtest.validation import validate_backtest_artifacts


def _copy_configs(tmp_path: Path) -> Path:
    project_root = Path(__file__).resolve().parents[1]
    src = project_root / "configs"
    dst = tmp_path / "configs"
    shutil.copytree(src, dst)
    return dst


def _write_runtime_overrides(config_dir: Path, **overrides: object) -> None:
    runtime_path = config_dir / "runtime.yaml"
    payload = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    payload.update(overrides)
    runtime_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_pairs_policy_overrides(config_dir: Path, **overrides: object) -> None:
    policy_path = config_dir / "pairs_policy.yaml"
    payload = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    payload.update(overrides)
    policy_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_phase2_metrics_artifacts_present(tmp_path: Path) -> None:
    config_dir = _copy_configs(tmp_path)
    _write_runtime_overrides(config_dir, phase2_pairs_gating_enabled=True)
    _write_pairs_policy_overrides(config_dir, lookback_bars=80)

    out_dir = run_synthetic_backtest(tmp_path / "phase2_metrics", config_dir=config_dir)
    ok, issues = validate_backtest_artifacts(out_dir, require_phase2=True)
    assert ok is True, str(issues)

    required = [
        "pairs_candidates.csv",
        "pairs_scan.csv",
        "pair_state_events.csv",
        "pnl_by_pair.csv",
        "phase2_demo_report.md",
    ]
    for name in required:
        assert (out_dir / name).exists()

    scan = pd.read_csv(out_dir / "pairs_scan.csv")
    assert not scan.empty
    assert {"pair", "p_value", "pair_status"}.issubset(set(scan.columns))

    report = (out_dir / "phase2_demo_report.md").read_text(encoding="utf-8")
    assert "Phase 2 Demo Report" in report
