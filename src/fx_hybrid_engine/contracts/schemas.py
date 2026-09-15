"""Canonical schema contracts shared across backtest and operations paths."""
from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class TabularSchema:
    """Simple typed schema definition for required contract fields."""

    name: str
    required_columns: tuple[str, ...]


BAR_SCHEMA = TabularSchema(
    name="BarSchema",
    required_columns=("timestamp", "symbol", "open", "high", "low", "close", "run_id"),
)

FEATURE_SCHEMA = TabularSchema(
    name="FeatureSchema",
    required_columns=("timestamp", "symbol", "run_id"),
)

SIGNAL_SCHEMA = TabularSchema(
    name="SignalSchema",
    required_columns=("timestamp", "symbol", "engine_source", "run_id"),
)

ORDER_SCHEMA = TabularSchema(
    name="OrderSchema",
    required_columns=("timestamp", "symbol", "order_type", "run_id"),
)

FILL_SCHEMA = TabularSchema(
    name="FillSchema",
    required_columns=("timestamp", "symbol", "run_id"),
)

ARTIFACTS_SCHEMA: dict[str, tuple[str, ...]] = {
    "walkforward_required_root_files": (
        "run_manifest.json",
        "splits.csv",
        "metrics_by_split.csv",
    ),
    "ops_required_streams": (
        "bars.parquet",
        "features.parquet",
        "signals.parquet",
        "targets.parquet",
        "orders.parquet",
        "fills.parquet",
        "equity_curve.parquet",
        "risk_events.parquet",
        "broker_events.jsonl",
        "reconciliation_events.jsonl",
        "run_manifest.json",
        "config_snapshot.yaml",
        "ops_summary.json",
    ),
}
