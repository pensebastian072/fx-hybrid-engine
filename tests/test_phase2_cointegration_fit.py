"""Phase 2 cointegration fit tests."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from fx_lean_engine.pairs.cointegration import fit_pair


def test_phase2_cointegration_fit_identifies_cointegrated_pair() -> None:
    rng = np.random.default_rng(7)
    n = 900
    x = np.cumsum(rng.normal(0.0, 0.01, size=n))
    y = 1.25 * x + rng.normal(0.0, 0.01, size=n)

    fit = fit_pair(
        y=y,
        x=x,
        lookback=500,
        pair=("EURUSD", "GBPUSD"),
        timestamp=datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert abs(fit.beta - 1.25) < 0.2
    assert 0.0 <= fit.p_value <= 1.0
    assert fit.p_value < 0.10
    assert fit.spread_std > 0.0


def test_phase2_cointegration_fit_rejects_random_walk_pair() -> None:
    rng = np.random.default_rng(19)
    n = 900
    x = np.cumsum(rng.normal(0.0, 0.02, size=n))
    y = np.cumsum(rng.normal(0.0, 0.02, size=n))

    fit = fit_pair(
        y=y,
        x=x,
        lookback=500,
        pair=("AUDUSD", "NZDUSD"),
        timestamp=datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert 0.0 <= fit.p_value <= 1.0
    assert fit.p_value > 0.05
