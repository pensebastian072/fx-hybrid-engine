"""Simple model version registry for scheduled refresh workflows."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_hybrid_engine.utils.config import ModelRegistryConfig


def _now() -> datetime:
    return datetime.now(UTC)


def _registry_path(root: str | Path) -> Path:
    out = Path(root)
    out.mkdir(parents=True, exist_ok=True)
    return out / "model_registry.jsonl"


def register_model_version(
    cfg: ModelRegistryConfig,
    *,
    run_id: str,
    model_type: str,
    model_version: str,
    training_window: str,
    feature_schema_version: str,
    data_hash: str,
    artifact_path: str,
    created_at_utc: str | None = None,
) -> Path:
    path = _registry_path(cfg.root)
    payload = {
        "run_id": run_id,
        "model_type": model_type,
        "model_version": model_version,
        "training_window": training_window,
        "feature_schema_version": feature_schema_version,
        "data_hash": data_hash,
        "artifact_path": artifact_path,
        "created_at_utc": created_at_utc or _now().isoformat(),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True))
        f.write("\n")
    return path


def load_registry(cfg: ModelRegistryConfig) -> list[dict[str, object]]:
    path = _registry_path(cfg.root)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def refresh_due(cfg: ModelRegistryConfig, *, now_utc: str | None = None) -> dict[str, bool]:
    now = datetime.fromisoformat(now_utc) if now_utc else _now()
    rows = load_registry(cfg)
    latest: dict[str, datetime] = {}
    for row in rows:
        mt = str(row.get("model_type", ""))
        ts = row.get("created_at_utc")
        if not mt or not ts:
            continue
        created = datetime.fromisoformat(str(ts))
        if mt not in latest or created > latest[mt]:
            latest[mt] = created

    due = {}
    thresholds = {
        "trend": cfg.trend_refresh_days,
        "hmm": cfg.hmm_refresh_days,
        "pairs": cfg.pairs_refresh_days,
    }
    for model_type, days in thresholds.items():
        age = now - latest.get(model_type, now - timedelta(days=9999))
        due[model_type] = age >= timedelta(days=int(days))
    return due
