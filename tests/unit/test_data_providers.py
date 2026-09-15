"""Unit tests for provider abstraction and cadence validation."""
from __future__ import annotations

import pytest

from fx_hybrid_engine.data.provider import fetch_multi_symbol
from fx_hybrid_engine.data.providers.factory import create_provider


def test_lean_history_provider_supports_15m():
    provider = create_provider("lean_history", seed=7)
    assert provider.supports_frequency("15m")
    frame = provider.get_history(["EURUSD"], start="2024-01-01", end="2024-01-02", frequency="15m")
    assert not frame.empty
    assert {"timestamp", "symbol", "open", "high", "low", "close"} <= set(frame.columns)


def test_fetch_multi_symbol_rejects_unsupported_frequency():
    with pytest.raises(ValueError, match="does not support bar frequency"):
        fetch_multi_symbol(
            symbols=["EURUSD"],
            start="2024-01-01",
            end="2024-01-02",
            source="openbb",
            provider="fmp",
            frequency="15m",
        )


def test_oanda_provider_stub_raises_not_implemented():
    provider = create_provider("oanda")
    with pytest.raises(NotImplementedError, match="Phase 1 stub"):
        provider.get_history(["EURUSD"], start="2024-01-01", end="2024-01-02", frequency="15m")
