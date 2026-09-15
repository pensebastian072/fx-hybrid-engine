"""Broker-neutral models for live execution adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class BrokerAccount:
    account_number: str
    account_type: str | None = None
    authority_level: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrokerBalance:
    account_number: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    account_number: str
    symbol: str
    quantity: float
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrokerOrderRequest:
    account_number: str
    symbol: str
    side: str
    quantity: float
    order_type: str = "market"
    raw: dict[str, Any] = field(default_factory=dict)


class LiveBrokerClient(Protocol):
    """Minimal broker interface for upcoming live-rail adapters."""

    name: str

    def list_accounts(self) -> list[BrokerAccount]:
        """Return the accounts available to the authenticated session."""

    def get_balances(self, account_number: str) -> BrokerBalance:
        """Return normalized balance details for one account."""

