"""QC ObjectStore persistence adapter with local JSON fallback."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _local_state_path(namespace: str) -> Path:
    safe = namespace.replace("/", "_")
    return Path("artifacts") / "qc_state" / f"{safe}.json"


def load_state(
    *,
    namespace: str,
    owner: object | None = None,
) -> dict[str, Any]:
    """Load state from QC ObjectStore when available, else local JSON fallback."""
    key = f"{namespace}/runtime_state"
    # QC path
    if owner is not None:
        store = getattr(owner, "ObjectStore", None)
        if store is not None:
            try:
                if bool(store.ContainsKey(key)):  # type: ignore[attr-defined]
                    payload = str(store.Read(key))  # type: ignore[attr-defined]
                    data = json.loads(payload) if payload else {}
                    if isinstance(data, dict):
                        return data
            except Exception:  # noqa: BLE001
                pass

    # Local fallback
    path = _local_state_path(namespace)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def save_state(
    *,
    namespace: str,
    payload: dict[str, Any],
    owner: object | None = None,
) -> None:
    """Persist state to QC ObjectStore when available, else local JSON fallback."""
    key = f"{namespace}/runtime_state"
    body = json.dumps(payload, sort_keys=True, default=str)

    if owner is not None:
        store = getattr(owner, "ObjectStore", None)
        if store is not None:
            try:
                store.Save(key, body)  # type: ignore[attr-defined]
                return
            except Exception:  # noqa: BLE001
                pass

    path = _local_state_path(namespace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")

