"""Backtest artifact contract validation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REQUIRED_CSV_NON_EMPTY = [
    "signals.csv",
    "orders.csv",
    "equity_curve.csv",
    "regime.csv",
    "features.csv",
    "targets.csv",
]
REQUIRED_PHASE2_CSV_NON_EMPTY = [
    "pairs_candidates.csv",
    "pairs_scan.csv",
    "pair_state_events.csv",
    "pnl_by_pair.csv",
]
REQUIRED_PHASE2_TEXT_NON_EMPTY = ["phase2_demo_report.md"]

REQUIRED_JSON_KEYS = {
    "metrics.json": [
        "run_id",
        "symbols",
        "resolution",
        "bar_interval_minutes",
        "start",
        "end",
        "signals_count",
        "orders_count",
        "trades_count",
        "max_gross_exposure",
        "avg_holding_bars",
        "turnover",
        "warnings_count",
        "errors_count",
    ],
    "run_manifest.json": [
        "run_id",
        "generated_at",
        "git_sha",
        "runtime_mode",
        "data_source",
        "config_hashes",
    ],
}
REQUIRED_YAML = ["config_snapshot.yaml"]


def _check_csv(path: Path, issues: list[str], require_non_empty: bool) -> pd.DataFrame | None:
    if not path.exists():
        issues.append(f"missing artifact: {path.name}")
        return None
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        issues.append(f"invalid CSV {path.name}: {exc}")
        return None
    if require_non_empty and frame.empty:
        issues.append(f"artifact empty: {path.name}")
    return frame


def _check_json(path: Path, required_keys: list[str], issues: list[str]) -> dict[str, object] | None:
    if not path.exists():
        issues.append(f"missing artifact: {path.name}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(f"invalid JSON {path.name}: {exc}")
        return None
    for key in required_keys:
        if key not in payload:
            issues.append(f"{path.name} missing key: {key}")
    return payload


def _check_non_empty_text(path: Path, issues: list[str]) -> None:
    if not path.exists():
        issues.append(f"missing artifact: {path.name}")
        return
    if not path.read_text(encoding="utf-8").strip():
        issues.append(f"artifact empty: {path.name}")


def validate_backtest_artifacts(run_dir: str | Path, require_phase2: bool = False) -> tuple[bool, list[str]]:
    """Validate expected artifacts and return (ok, issues)."""
    path = Path(run_dir)
    issues: list[str] = []

    if not path.exists():
        return False, [f"run_dir missing: {path}"]

    csv_frames: dict[str, pd.DataFrame] = {}
    for name in REQUIRED_CSV_NON_EMPTY:
        frame = _check_csv(path / name, issues, require_non_empty=True)
        if frame is not None:
            csv_frames[name] = frame

    features = csv_frames.get("features.csv")
    if features is not None and not features.empty:
        numeric = features.select_dtypes(include=[np.number])
        if numeric.isna().any().any():
            issues.append("features.csv contains NaN values")
        if np.isinf(numeric.to_numpy(dtype=float)).any():
            issues.append("features.csv contains infinite values")

    for name, keys in REQUIRED_JSON_KEYS.items():
        _check_json(path / name, keys, issues)

    for name in REQUIRED_YAML:
        file_path = path / name
        if not file_path.exists():
            issues.append(f"missing artifact: {name}")
            continue
        try:
            payload = yaml.safe_load(file_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not payload:
                issues.append(f"invalid YAML {name}: expected non-empty mapping")
        except Exception as exc:
            issues.append(f"invalid YAML {name}: {exc}")

    if require_phase2:
        for name in REQUIRED_PHASE2_CSV_NON_EMPTY:
            _check_csv(path / name, issues, require_non_empty=True)
        for name in REQUIRED_PHASE2_TEXT_NON_EMPTY:
            _check_non_empty_text(path / name, issues)

    return len(issues) == 0, issues
