"""YAML config loaders with strict key validation."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, TypeVar

import yaml

from fx_lean_engine.config.models import (
    BacktestConfig,
    PairsConfig,
    PairsPolicyConfig,
    RegimeConfig,
    RuntimeConfig,
    UniverseConfig,
)

T = TypeVar("T")


class ConfigError(ValueError):
    """Raised on invalid config payloads."""


def _read_yaml(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.exists():
        raise ConfigError(f"Config not found: {resolved}")
    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config must be a top-level mapping: {resolved}")
    return data


def _build_dataclass(data: dict[str, Any], cls: type[T], path: str | Path) -> T:
    allowed = {item.name for item in fields(cls)}
    unknown = sorted(set(data.keys()).difference(allowed))
    if unknown:
        raise ConfigError(f"Unknown keys in {path}: {', '.join(unknown)}")
    try:
        return cls(**data)
    except Exception as exc:
        raise ConfigError(f"Invalid config {path}: {exc}") from exc


def load_universe_config(path: str | Path) -> UniverseConfig:
    """Load universe config from YAML."""
    return _build_dataclass(_read_yaml(path), UniverseConfig, path)


def load_pairs_config(path: str | Path) -> PairsConfig:
    """Load pairs config from YAML."""
    return _build_dataclass(_read_yaml(path), PairsConfig, path)


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    """Load runtime config from YAML."""
    return _build_dataclass(_read_yaml(path), RuntimeConfig, path)


def load_backtest_config(path: str | Path) -> BacktestConfig:
    """Load backtest config from YAML."""
    return _build_dataclass(_read_yaml(path), BacktestConfig, path)


def load_pairs_policy_config(path: str | Path) -> PairsPolicyConfig:
    """Load phase 2 pairs policy from YAML."""
    return _build_dataclass(_read_yaml(path), PairsPolicyConfig, path)


def load_pairs_policy_with_overrides(
    base_path: str | Path,
    overrides_path: str | Path | None = None,
) -> PairsPolicyConfig:
    """Load phase 2 policy and apply optional trader override mapping."""
    base_data = _read_yaml(base_path)
    merged = dict(base_data)
    if overrides_path is not None and Path(overrides_path).exists():
        override_data = _read_yaml(overrides_path)
        for key, value in override_data.items():
            if value is None:
                continue
            merged[key] = value
    return _build_dataclass(merged, PairsPolicyConfig, base_path)


def load_regime_config(path: str | Path) -> RegimeConfig:
    """Load regime config from YAML."""
    return _build_dataclass(_read_yaml(path), RegimeConfig, path)
