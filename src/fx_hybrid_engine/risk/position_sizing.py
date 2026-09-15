"""Position sizing: vol-targeting and beta-neutral helpers."""
from __future__ import annotations
import numpy as np
import pandas as pd

from fx_hybrid_engine.utils.config import RiskConfig


def vol_target_scalar(
    realized_vol_annual: float,
    target_vol_annual: float,
    max_leverage: float = 3.0,
) -> float:
    """Return a scalar multiplier to hit target annual vol.

    scalar = target_vol / realized_vol, clamped to [0, max_leverage].
    """
    if realized_vol_annual <= 0:
        return 0.0
    scalar = target_vol_annual / realized_vol_annual
    return float(np.clip(scalar, 0.0, max_leverage))


def size_pairs_legs(
    base_size: float,
    beta: float,
    max_position_pct: float,
) -> tuple[float, float]:
    """Return (size_a, size_b) for a beta-neutral pairs trade.

    size_a = min(base_size, max_position_pct)
    size_b = size_a * beta
    """
    size_a = min(base_size, max_position_pct)
    size_b = size_a * abs(beta)
    return size_a, size_b


def apply_vol_sizing(
    weights: dict[str, float],
    realized_vols: dict[str, float],
    config: RiskConfig,
) -> dict[str, float]:
    """Scale each instrument weight by its vol-targeting scalar.

    Total notional is then re-capped by max_leverage.
    """
    scaled: dict[str, float] = {}
    for sym, w in weights.items():
        rv = realized_vols.get(sym, 0.0)
        if rv > 0:
            scalar = vol_target_scalar(rv, config.vol_target_annual, config.max_leverage)
        else:
            scalar = 1.0
        scaled[sym] = w * scalar

    # Cap total absolute notional to max_leverage
    total = sum(abs(v) for v in scaled.values())
    if total > config.max_leverage:
        factor = config.max_leverage / total
        scaled = {k: v * factor for k, v in scaled.items()}

    return scaled
