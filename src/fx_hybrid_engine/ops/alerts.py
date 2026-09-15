"""Append-only alert logging stubs for operational monitoring."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fx_hybrid_engine.utils.config import AlertsConfig

SEVERITY_ORDER = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "error": 40,
    "critical": 50,
}


def _ts() -> str:
    return datetime.now(UTC).isoformat()


def _should_emit(level: str, min_level: str) -> bool:
    return SEVERITY_ORDER.get(level.lower(), 30) >= SEVERITY_ORDER.get(min_level.lower(), 30)


def append_alert(
    run_dir: str | Path,
    *,
    run_id: str,
    severity: str,
    alert_type: str,
    message: str,
    details: dict[str, object] | None = None,
    cfg: AlertsConfig | None = None,
) -> Path | None:
    config = cfg or AlertsConfig()
    if not config.enabled:
        return None
    if not _should_emit(severity, config.min_severity):
        return None

    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / config.output_path
    payload = {
        "timestamp": _ts(),
        "run_id": run_id,
        "severity": severity.lower(),
        "type": alert_type,
        "message": message,
        "details": details or {},
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True))
        f.write("\n")
    return path

