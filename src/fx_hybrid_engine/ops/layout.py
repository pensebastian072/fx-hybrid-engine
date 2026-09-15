"""Filesystem layout helpers for Phase 6+ operational artifacts."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def build_run_dir(
    output_root: str | Path,
    *,
    mode: str,
    run_id: str,
    run_date_utc: datetime | None = None,
) -> Path:
    dt = run_date_utc or datetime.now(UTC)
    return Path(output_root) / mode / dt.date().isoformat() / run_id


def build_legacy_run_dir(legacy_output_root: str | Path, run_id: str) -> Path:
    return Path(legacy_output_root) / run_id


def resolve_run_dir(
    run_id: str,
    *,
    output_root: str | Path,
    mode: str,
    legacy_output_root: str | Path,
) -> Path:
    base = Path(output_root) / mode
    if base.exists():
        matches = sorted(base.glob(f"*/{run_id}"))
        if matches:
            return matches[-1]
    legacy = build_legacy_run_dir(legacy_output_root, run_id)
    if legacy.exists():
        return legacy
    return build_run_dir(output_root, mode=mode, run_id=run_id)

