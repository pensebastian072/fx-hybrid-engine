"""Artifact contract validation for walk-forward split run directories."""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

RUN_MANIFEST_REQUIRED_KEYS = [
    "wf_run_id",
    "created_at_utc",
    "config_path",
    "git_commit",
    "config_hash",
    "schema_version",
    "seed",
    "precompute_enabled",
    "mode_reuse_enabled",
    "skip_robustness",
    "data_profile",
    "symbols",
    "pair_list",
    "trend_symbols",
    "split_params",
    "cost_params",
    "cache_fingerprint",
    "pipeline_version",
]

REQUIRED_BASENAMES = [
    "signals",
    "trades",
    "fills",
    "equity_curve",
    "metrics.json",
    "config_snapshot.yaml",
    "engine_allocations",
]

REGIME_ALIASES = ["regime_posteriors", "regime"]

ROOT_REQUIRED_FILES = [
    "splits.csv",
    "metrics_by_split.csv",
    "pnl_attribution_engine.csv",
    "pnl_attribution_regime.csv",
    "pnl_attribution_engine_x_regime.csv",
]

SPLIT_REQUIRED_FILES = [
    "pairs_candidates.csv",
    "pairs_scan.csv",
    "pairs_diagnostics.csv",
    "pair_state_events.csv",
    "pair_state_snapshot.json",
]

SPLIT_REGIME_QA_FILES = [
    "regime_events.csv",
    "regime_summary.json",
    "hmm_state_map.json",
]

METRICS_BY_SPLIT_REQUIRED = [
    "split_idx",
    "mode",
    "total_return",
    "sharpe",
    "max_drawdown",
    "trades",
    "precompute_enabled",
    "mode_reuse_enabled",
    "cache_fingerprint",
    "pipeline_version",
]

ATTRIBUTION_NUMERIC_COLUMNS: dict[str, list[str]] = {
    "pnl_attribution_engine.csv": ["n_trades", "total_pnl", "win_rate", "pnl_share"],
    "pnl_attribution_regime.csv": ["n_trades", "total_pnl", "win_rate", "pnl_share"],
    "pnl_attribution_engine_x_regime.csv": ["n_trades", "total_pnl", "win_rate", "pnl_share_within_engine"],
}

TABULAR_COLUMNS: dict[str, list[str]] = {
    "signals": ["timestamp", "symbol", "direction", "size", "engine_source", "mode"],
    "trades": [
        "entry_timestamp",
        "exit_timestamp",
        "symbol",
        "engine_source",
        "entry_regime",
        "exit_regime",
        "pnl",
        "mode",
    ],
    "fills": ["timestamp", "symbol", "delta_weight", "price", "engine_source", "regime_label", "mode"],
    "equity_curve": ["timestamp", "equity", "net_return", "gross_return", "turnover", "costs", "mode"],
    "engine_allocations": ["timestamp", "pairs_alloc", "trend_alloc", "total_alloc", "regime_label", "mode"],
}


@dataclass(slots=True)
class ValidationIssue:
    level: str
    path: Path
    message: str


def validate_run_manifest(root_dir: str | Path) -> list[ValidationIssue]:
    """Validate root-level run manifest required for full reproducibility."""
    root = Path(root_dir)
    manifest_path = root / "run_manifest.json"
    issues: list[ValidationIssue] = []
    if not manifest_path.exists():
        return [ValidationIssue("error", manifest_path, "Missing required root artifact: run_manifest.json")]
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return [ValidationIssue("error", manifest_path, f"Invalid run_manifest.json: {exc}")]

    missing = [k for k in RUN_MANIFEST_REQUIRED_KEYS if k not in data]
    if missing:
        issues.append(ValidationIssue("error", manifest_path, f"Missing required run_manifest keys: {missing}"))
        return issues

    if not isinstance(data["wf_run_id"], str) or not data["wf_run_id"]:
        issues.append(ValidationIssue("error", manifest_path, "run_manifest.wf_run_id must be a non-empty string"))
    if not isinstance(data["config_path"], str) or not data["config_path"]:
        issues.append(ValidationIssue("error", manifest_path, "run_manifest.config_path must be a non-empty string"))
    if not isinstance(data["git_commit"], str) or not data["git_commit"]:
        issues.append(ValidationIssue("error", manifest_path, "run_manifest.git_commit must be a non-empty string"))
    if not isinstance(data["config_hash"], str) or len(data["config_hash"]) != 64:
        issues.append(
            ValidationIssue(
                "error",
                manifest_path,
                "run_manifest.config_hash must be a 64-char sha256 hex string",
            )
        )
    if not isinstance(data["schema_version"], str) or not data["schema_version"]:
        issues.append(
            ValidationIssue(
                "error",
                manifest_path,
                "run_manifest.schema_version must be a non-empty string",
            )
        )
    if not isinstance(data["seed"], int):
        issues.append(ValidationIssue("error", manifest_path, "run_manifest.seed must be an integer"))
    for key in ("precompute_enabled", "mode_reuse_enabled", "skip_robustness"):
        if not isinstance(data[key], bool):
            issues.append(ValidationIssue("error", manifest_path, f"run_manifest.{key} must be boolean"))
    for key in ("symbols", "pair_list", "trend_symbols"):
        if not isinstance(data[key], list):
            issues.append(ValidationIssue("error", manifest_path, f"run_manifest.{key} must be a list"))
    if not isinstance(data["split_params"], dict):
        issues.append(ValidationIssue("error", manifest_path, "run_manifest.split_params must be an object"))
    else:
        split_missing = [
            key
            for key in ("train_window_days", "test_window_days", "step_days", "max_splits", "generated_splits")
            if key not in data["split_params"]
        ]
        if split_missing:
            issues.append(
                ValidationIssue(
                    "error",
                    manifest_path,
                    f"run_manifest.split_params missing keys: {split_missing}",
                )
            )
    if not isinstance(data["cost_params"], dict):
        issues.append(ValidationIssue("error", manifest_path, "run_manifest.cost_params must be an object"))
    if not isinstance(data["cache_fingerprint"], str) or len(data["cache_fingerprint"]) != 64:
        issues.append(
            ValidationIssue(
                "error",
                manifest_path,
                "run_manifest.cache_fingerprint must be a 64-char sha256 hex string",
            )
        )
    if not isinstance(data["pipeline_version"], str) or not data["pipeline_version"]:
        issues.append(
            ValidationIssue(
                "error",
                manifest_path,
                "run_manifest.pipeline_version must be a non-empty string",
            )
        )

    created = pd.to_datetime(data["created_at_utc"], utc=True, errors="coerce")
    if pd.isna(created):
        issues.append(ValidationIssue("error", manifest_path, "run_manifest.created_at_utc must be an ISO-8601 UTC timestamp"))
    return issues


def _try_load_tabular(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported tabular format for {path}")


def _find_optional_tabular(run_dir: Path, stem: str) -> Path | None:
    for ext in (".csv", ".parquet"):
        cand = run_dir / f"{stem}{ext}"
        if cand.exists():
            return cand
    return None


def _find_required_path(run_dir: Path, required_name: str) -> Path | None:
    if required_name.endswith(".json") or required_name.endswith(".yaml"):
        cand = run_dir / required_name
        return cand if cand.exists() else None
    return _find_optional_tabular(run_dir, required_name)


def _validate_timestamps(df: pd.DataFrame, col: str, path: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if col not in df.columns:
        return issues
    ts = pd.to_datetime(df[col], utc=True, errors="coerce")
    if ts.isna().any():
        issues.append(ValidationIssue("error", path, f"Column '{col}' contains non-parseable timestamps"))
        return issues
    if not ts.is_monotonic_increasing:
        issues.append(ValidationIssue("error", path, f"Column '{col}' must be monotonic increasing"))
    return issues


def validate_split_mode_run(run_dir: str | Path) -> list[ValidationIssue]:
    """Validate one split/mode run directory against the artifact contract."""
    path = Path(run_dir)
    issues: list[ValidationIssue] = []

    if not path.exists() or not path.is_dir():
        return [ValidationIssue("error", path, "Run directory does not exist or is not a directory")]

    # Required files
    for required in REQUIRED_BASENAMES:
        resolved = _find_required_path(path, required)
        if resolved is None:
            issues.append(ValidationIssue("error", path, f"Missing required artifact: {required}(.csv|.parquet)"))

    if _find_optional_tabular(path, "regime_posteriors") is None and _find_optional_tabular(path, "regime") is None:
        issues.append(ValidationIssue("error", path, "Missing required artifact: regime_posteriors(.csv|.parquet) OR regime(.csv|.parquet)"))

    # Validate tabular files and key columns
    for stem, columns in TABULAR_COLUMNS.items():
        tab_path = _find_optional_tabular(path, stem)
        if tab_path is None:
            continue
        try:
            df = _try_load_tabular(tab_path)
        except Exception as exc:
            issues.append(ValidationIssue("error", tab_path, f"Failed to load: {exc}"))
            continue
        missing = [c for c in columns if c not in df.columns]
        if missing:
            issues.append(ValidationIssue("error", tab_path, f"Missing required columns: {missing}"))
            continue
        key_cols = [c for c in columns if c not in ("pair_id",)]
        null_keys = [c for c in key_cols if c in df.columns and df[c].isna().any()]
        if null_keys:
            issues.append(ValidationIssue("error", tab_path, f"Null values in required columns: {null_keys}"))
        if "timestamp" in df.columns:
            issues.extend(_validate_timestamps(df, "timestamp", tab_path))

    # metrics.json and config snapshot parse checks
    metrics_path = path / "metrics.json"
    if metrics_path.exists():
        try:
            with open(metrics_path, encoding="utf-8") as f:
                data = json.load(f)
            for key in ("total_return", "sharpe", "max_drawdown", "trades"):
                if key not in data:
                    issues.append(ValidationIssue("error", metrics_path, f"Missing key in metrics.json: {key}"))
        except Exception as exc:
            issues.append(ValidationIssue("error", metrics_path, f"Invalid metrics.json: {exc}"))

    cfg_path = path / "config_snapshot.yaml"
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                yaml.safe_load(f)
        except Exception as exc:
            issues.append(ValidationIssue("error", cfg_path, f"Invalid config snapshot YAML: {exc}"))

    return issues


def _regime_qa_enabled_for_split(split_dir: Path) -> bool:
    snapshot_path = split_dir / "hybrid" / "config_snapshot.yaml"
    if not snapshot_path.exists():
        return True
    try:
        with open(snapshot_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return True
    return bool(((data.get("config") or {}).get("regime_qa") or {}).get("enabled", True))


def validate_split_root(split_dir: str | Path) -> list[ValidationIssue]:
    """Validate split-root additive artifacts produced by phase2/3/5 flows."""
    path = Path(split_dir)
    issues: list[ValidationIssue] = []
    if not path.exists() or not path.is_dir():
        return [ValidationIssue("error", path, "Split root does not exist or is not a directory")]

    for rel in SPLIT_REQUIRED_FILES:
        target = path / rel
        if not target.exists():
            issues.append(ValidationIssue("error", target, f"Missing split-root artifact: {rel}"))
    if _regime_qa_enabled_for_split(path):
        for rel in SPLIT_REGIME_QA_FILES:
            target = path / rel
            if not target.exists():
                issues.append(ValidationIssue("error", target, f"Missing split-root artifact: {rel}"))

    snapshot_path = path / "pair_state_snapshot.json"
    if snapshot_path.exists():
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                issues.append(ValidationIssue("error", snapshot_path, "pair_state_snapshot.json must be a JSON object"))
        except Exception as exc:
            issues.append(ValidationIssue("error", snapshot_path, f"Invalid pair_state_snapshot.json: {exc}"))
    return issues


def _validate_root_tables(root_dir: str | Path) -> list[ValidationIssue]:
    root = Path(root_dir)
    issues: list[ValidationIssue] = []
    for rel in ROOT_REQUIRED_FILES:
        target = root / rel
        if not target.exists():
            issues.append(ValidationIssue("error", target, f"Missing root artifact: {rel}"))

    metrics_path = root / "metrics_by_split.csv"
    if metrics_path.exists():
        try:
            metrics = pd.read_csv(metrics_path)
        except Exception as exc:
            issues.append(ValidationIssue("error", metrics_path, f"Failed to parse metrics_by_split.csv: {exc}"))
            metrics = pd.DataFrame()
        if not metrics.empty:
            missing = [c for c in METRICS_BY_SPLIT_REQUIRED if c not in metrics.columns]
            if missing:
                issues.append(ValidationIssue("error", metrics_path, f"Missing metrics_by_split columns: {missing}"))
            else:
                for col in ["split_idx", "mode", "total_return", "sharpe", "max_drawdown", "trades"]:
                    if metrics[col].isna().any():
                        issues.append(ValidationIssue("error", metrics_path, f"metrics_by_split has NaNs in '{col}'"))
        else:
            issues.append(ValidationIssue("error", metrics_path, "metrics_by_split.csv must contain at least one row"))

    for rel, cols in ATTRIBUTION_NUMERIC_COLUMNS.items():
        path = root / rel
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            issues.append(ValidationIssue("error", path, f"Failed to parse {rel}: {exc}"))
            continue
        if df.empty:
            continue
        missing = [c for c in cols if c not in df.columns]
        if missing:
            issues.append(ValidationIssue("error", path, f"Missing required attribution columns: {missing}"))
            continue
        for col in cols:
            if df[col].isna().any():
                issues.append(ValidationIssue("error", path, f"Attribution column '{col}' contains NaN values"))
    return issues


def discover_split_mode_dirs(root_dir: str | Path) -> list[Path]:
    """Discover split/mode artifact directories by finding directories containing metrics.json."""
    root = Path(root_dir)
    if not root.exists():
        return []
    dirs: list[Path] = []
    for metrics in root.rglob("metrics.json"):
        dirs.append(metrics.parent)
    return sorted(set(dirs))


def validate_run_tree(root_dir: str | Path) -> tuple[bool, list[ValidationIssue]]:
    """Validate all split/mode directories under the given run root."""
    issues = validate_run_manifest(root_dir)
    issues.extend(_validate_root_tables(root_dir))
    mode_dirs = discover_split_mode_dirs(root_dir)
    if not mode_dirs:
        issues.append(
            ValidationIssue(
                "error",
                Path(root_dir),
                "No split/mode run directories found (metrics.json not discovered)",
            )
        )
        return False, issues

    split_roots = sorted({d.parent for d in mode_dirs if d.parent.name.startswith("split_")})
    if not split_roots:
        issues.append(ValidationIssue("error", Path(root_dir), "No split roots found under run directory"))
    else:
        for split_root in split_roots:
            issues.extend(validate_split_root(split_root))

    for run_dir in mode_dirs:
        issues.extend(validate_split_mode_run(run_dir))

    ok = not any(i.level == "error" for i in issues)
    return ok, issues


def render_issues(issues: Iterable[ValidationIssue]) -> str:
    lines = []
    for issue in issues:
        lines.append(f"[{issue.level.upper()}] {issue.path}: {issue.message}")
    return "\n".join(lines)
