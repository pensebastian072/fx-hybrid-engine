"""Local data source validation."""

from __future__ import annotations

from pathlib import Path


def ensure_local_data_supported(local_data_dir: str | Path | None) -> None:
    """Raise RuntimeError if local data is configured but the directory is absent."""
    if not local_data_dir:
        raise RuntimeError(
            "data_source='local' requires runtime_cfg.local_data_dir to be set."
        )
    path = Path(str(local_data_dir))
    if not path.exists():
        raise RuntimeError(
            f"local_data_dir '{path}' does not exist. "
            "Please provide a valid path to the local OHLCV data directory."
        )
