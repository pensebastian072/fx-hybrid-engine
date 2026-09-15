"""Universe FX tests."""

from __future__ import annotations

from dataclasses import dataclass

from fx_lean_engine.data.universe import SubscriptionRegistry, add_forex_for_alias, normalize_forex_pair


@dataclass
class _Security:
    Symbol: str


class _Algo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.logs: list[str] = []

    def AddForex(self, pair: str, resolution: object) -> _Security:  # noqa: N802
        self.calls.append((pair, resolution))
        return _Security(Symbol=f"SYM:{pair}")

    def Log(self, message: str) -> None:  # noqa: N802
        self.logs.append(message)


def test_normalize_forex_pair_aliases() -> None:
    assert normalize_forex_pair("eur/usd") == "EURUSD"
    assert normalize_forex_pair("EURUSD") == "EURUSD"


def test_add_forex_for_alias_registers_symbol() -> None:
    algo = _Algo()
    registry = SubscriptionRegistry()

    symbol = add_forex_for_alias(algo, "eur/usd", "Minute", registry)

    assert symbol == "SYM:EURUSD"
    assert algo.calls == [("EURUSD", "Minute")]
    assert registry.alias_to_canonical["EUR/USD"] == "EURUSD"
    assert registry.canonical_to_symbol["EURUSD"] == "SYM:EURUSD"
    assert any("FX_SUBSCRIBE" in line for line in algo.logs)
