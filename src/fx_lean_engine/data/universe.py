"""FX pair subscription registry and universe helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def normalize_forex_pair(alias: str) -> str:
    """Normalize a forex pair string to a canonical 6-char upper-case form.

    Examples:
        ``"eur/usd"`` → ``"EURUSD"``
        ``"EURUSD"``  → ``"EURUSD"``
    """
    return alias.upper().replace("/", "").replace("-", "").replace("_", "").strip()


@dataclass
class SubscriptionRegistry:
    """Maps pair aliases and canonical forms to LEAN symbol objects."""

    alias_to_canonical: dict[str, str] = field(default_factory=dict)
    canonical_to_symbol: dict[str, Any] = field(default_factory=dict)


def add_forex_for_alias(
    algo: Any,
    alias: str,
    resolution: Any,
    registry: SubscriptionRegistry,
) -> Any:
    """Call *algo.AddForex* for *alias*, register the result, and return the symbol."""
    canonical = normalize_forex_pair(alias)
    symbol_obj = algo.AddForex(canonical, resolution)
    # In LEAN, AddForex returns a Symbol object; expose the underlying Symbol attribute
    # if present (e.g. in stub environments), otherwise use the object directly.
    symbol = getattr(symbol_obj, "Symbol", symbol_obj)
    # Preserve the original alias in the registry
    upper_alias = alias.upper()
    registry.alias_to_canonical[upper_alias] = canonical
    registry.canonical_to_symbol[canonical] = symbol
    if hasattr(algo, "Log"):
        algo.Log(f"FX_SUBSCRIBE canonical={canonical} alias={upper_alias}")
    return symbol
