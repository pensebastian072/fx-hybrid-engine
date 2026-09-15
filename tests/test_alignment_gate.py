"""Unit tests for cross-engine signal alignment gate (Task 3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_lean_engine.orchestration.pipeline import build_runtime_from_configs
from fx_lean_engine.types import Bar, PairsSignal, RegimeState, TradeIntent, TrendSignal


class _FlatPairsEngine:
    """Always-flat pairs engine — emits no intents."""

    def __init__(self, pairs):
        self.pairs = list(pairs)

    def update(self, *_args, **_kwargs):
        return [], []


class _FlatTrendEngine:
    """Always-flat trend engine — emits no intents."""

    def update(self, snapshot):
        return [
            TrendSignal(symbol=s, p_up=0.5, p_down=0.5, confidence=0.0, direction="FLAT")
            for s in snapshot
        ], []


class _AlwaysLongTrendEngine:
    """Emits a LONG open intent for every symbol every bar."""

    def update(self, snapshot):
        sigs = []
        intents = []
        for sym in sorted(snapshot.keys()):
            sigs.append(TrendSignal(symbol=sym, p_up=0.7, p_down=0.3, confidence=0.4, direction="LONG"))
            intents.append(
                TradeIntent(
                    engine="trend",
                    action="open",
                    symbol=sym,
                    pair=None,
                    direction="LONG",
                    notional_pct_nav=0.05,
                    confidence=0.4,
                    reason="TREND_SIGNAL",
                )
            )
        return sigs, intents


class _ActivePairsEngine:
    """Emits one pairs open intent involving EURUSD every bar.

    Uses the first real pair when available; falls back to a synthetic
    (EURUSD, GBPUSD) pair so the test works even with a single active symbol.
    """

    _FALLBACK_PAIR = ("EURUSD", "GBPUSD")

    def __init__(self, pairs):
        self.pairs = list(pairs)

    def update(self, snapshot, timestamp=None, pair_status_map=None):
        pair = self.pairs[0] if self.pairs else self._FALLBACK_PAIR
        sig = PairsSignal(pair=pair, zscore=2.5, hedge_ratio=1.0, direction="LONG", confidence=0.5)
        intent = TradeIntent(
            engine="pairs",
            action="open",
            symbol=None,
            pair=pair,
            direction="LONG",
            notional_pct_nav=0.05,
            confidence=0.5,
            reason="PAIRS_SIGNAL",
        )
        return [sig], [intent]


class _StubRegimeEngine:
    def update(self, *_args, **_kwargs) -> RegimeState:
        return RegimeState(
            state="TREND",
            p_trend=0.8,
            p_chop=0.1,
            p_risk_off=0.1,
            trend_weight=1.0,
            pairs_weight=1.0,
        )


CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"
_T0 = datetime(2025, 1, 1, tzinfo=UTC)


def _make_bar(symbol: str, i: int, close: float) -> Bar:
    return Bar(
        symbol=symbol,
        start=_T0 + timedelta(minutes=15 * i),
        end=_T0 + timedelta(minutes=15 * (i + 1)),
        open=close * 0.9995,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=1000.0,
    )


def test_alignment_gate_blocks_trend_when_no_pairs() -> None:
    """With require_signal_alignment=True and no pairs signal, trend opens must be blocked."""
    runtime = build_runtime_from_configs(
        config_dir=CONFIG_DIR,
        active_symbols=["EURUSD"],
        pairs_lookback_override=20,
        pairs_engine_factory=lambda pairs, lb, pc, rc, syms: _FlatPairsEngine(pairs),
        trend_engine_factory=lambda syms, rc: _AlwaysLongTrendEngine(),
        regime_engine_factory=lambda syms, rc: _StubRegimeEngine(),
        runtime_overrides={"require_signal_alignment": True},
    )

    close = 1.1
    for i in range(40):
        close *= 1.0001
        runtime.on_consolidated_bar(_make_bar("EURUSD", i, close))

    approved_opens = [
        r
        for r in runtime.artifacts.orders
        if r.get("status") == "approved" and r.get("action") == "open" and r.get("engine") == "trend"
    ]
    assert len(approved_opens) == 0, (
        "alignment gate should block all trend opens when no pairs signal is present"
    )

    alignment_blocked = [
        r
        for r in runtime.artifacts.risk_events
        if r.get("reason") in {"ALIGNMENT_GATE", "ALIGNMENT_LOW_CONFIDENCE"}
    ]
    assert len(alignment_blocked) > 0, "ALIGNMENT_GATE risk events must be emitted"


def test_alignment_gate_passes_trend_when_pairs_signal_present() -> None:
    """With require_signal_alignment=True and a matching pairs signal, trend opens must pass."""
    runtime = build_runtime_from_configs(
        config_dir=CONFIG_DIR,
        active_symbols=["EURUSD"],
        pairs_lookback_override=20,
        pairs_engine_factory=lambda pairs, lb, pc, rc, syms: _ActivePairsEngine(pairs),
        trend_engine_factory=lambda syms, rc: _AlwaysLongTrendEngine(),
        regime_engine_factory=lambda syms, rc: _StubRegimeEngine(),
        runtime_overrides={"require_signal_alignment": True},
    )

    close = 1.1
    for i in range(40):
        close *= 1.0001
        runtime.on_consolidated_bar(_make_bar("EURUSD", i, close))

    approved_opens = [
        r
        for r in runtime.artifacts.orders
        if r.get("status") == "approved" and r.get("action") == "open" and r.get("engine") == "trend"
    ]
    # With a matching pairs signal for EURUSD the gate should pass the trend opens.
    assert len(approved_opens) > 0, "trend opens should pass when a pairs signal covers the symbol"


def test_alignment_gate_disabled_by_default() -> None:
    """With require_signal_alignment=False (default) trend opens pass without pairs."""
    runtime = build_runtime_from_configs(
        config_dir=CONFIG_DIR,
        active_symbols=["EURUSD"],
        pairs_lookback_override=20,
        pairs_engine_factory=lambda pairs, lb, pc, rc, syms: _FlatPairsEngine(pairs),
        trend_engine_factory=lambda syms, rc: _AlwaysLongTrendEngine(),
        regime_engine_factory=lambda syms, rc: _StubRegimeEngine(),
    )

    close = 1.1
    for i in range(40):
        close *= 1.0001
        runtime.on_consolidated_bar(_make_bar("EURUSD", i, close))

    approved_opens = [
        r
        for r in runtime.artifacts.orders
        if r.get("status") == "approved" and r.get("action") == "open" and r.get("engine") == "trend"
    ]
    assert len(approved_opens) > 0, "trend opens should pass without alignment gate"
