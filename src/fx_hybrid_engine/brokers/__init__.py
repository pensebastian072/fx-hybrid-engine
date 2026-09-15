"""Broker abstractions and broker-specific adapters."""

from __future__ import annotations

from typing import Any

from fx_hybrid_engine.brokers.base import (
    BrokerAccount,
    BrokerBalance,
    BrokerOrderRequest,
    BrokerPosition,
    LiveBrokerClient,
)
from fx_hybrid_engine.brokers.tastytrade import TastytradeApiClient, TastytradeApiError


def run_tastytrade_live_session(*args: Any, **kwargs: Any):
    from fx_hybrid_engine.brokers.tastytrade_live import (
        run_tastytrade_live_session as _run_tastytrade_live_session,
    )

    return _run_tastytrade_live_session(*args, **kwargs)

__all__ = [
    "BrokerAccount",
    "BrokerBalance",
    "BrokerOrderRequest",
    "BrokerPosition",
    "LiveBrokerClient",
    "TastytradeApiClient",
    "TastytradeApiError",
    "run_tastytrade_live_session",
]
