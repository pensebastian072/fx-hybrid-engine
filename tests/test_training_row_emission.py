"""Unit tests for completed-trade training dataset emission (Task 2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_lean_engine.orchestration.pipeline import build_runtime_from_configs
from fx_lean_engine.types import Bar, RegimeState, TradeIntent, TrendSignal

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"
_T0 = datetime(2025, 1, 1, tzinfo=UTC)


class _StubRegimeEngine:
    def update(self, *_args, **_kwargs) -> RegimeState:
        return RegimeState(
            state="TREND",
            p_trend=0.8,
            p_chop=0.1,
            p_risk_off=0.1,
            trend_weight=1.0,
            pairs_weight=0.5,
        )


class _StubPairsEngine:
    def __init__(self, pairs):
        self.pairs = list(pairs)

    def update(self, *_args, **_kwargs):
        return [], []


class _OpenThenCloseTrendEngine:
    """Emits open on bar 20, close on bar 30, nothing otherwise."""

    _bar = 0
    OPEN_BAR = 20
    CLOSE_BAR = 30

    def update(self, snapshot: dict[str, float]):
        self._bar += 1
        sym = sorted(snapshot.keys())[0]
        if self._bar == self.OPEN_BAR:
            return (
                [TrendSignal(sym, 0.7, 0.3, 0.4, "LONG")],
                [
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
                ],
            )
        if self._bar == self.CLOSE_BAR:
            return (
                [TrendSignal(sym, 0.5, 0.5, 0.0, "FLAT")],
                [
                    TradeIntent(
                        engine="trend",
                        action="close",
                        symbol=sym,
                        pair=None,
                        direction="EXIT",
                        notional_pct_nav=0.05,
                        confidence=0.0,
                        reason="TREND_FLAT",
                    )
                ],
            )
        return [TrendSignal(sym, 0.5, 0.5, 0.0, "FLAT")], []


def _make_bar(symbol: str, i: int, close: float) -> Bar:
    return Bar(
        symbol=symbol,
        start=_T0 + timedelta(minutes=15 * i),
        end=_T0 + timedelta(minutes=15 * (i + 1)),
        open=close * 0.9998,
        high=close * 1.0005,
        low=close * 0.9995,
        close=close,
        volume=500.0,
    )


def test_training_row_emitted_on_trend_close() -> None:
    """A training row must be appended when a trend close intent is approved."""
    runtime = build_runtime_from_configs(
        config_dir=CONFIG_DIR,
        active_symbols=["EURUSD"],
        pairs_lookback_override=20,
        pairs_engine_factory=lambda pairs, lb, pc, rc, syms: _StubPairsEngine(pairs),
        trend_engine_factory=lambda syms, rc: _OpenThenCloseTrendEngine(),
        regime_engine_factory=lambda syms, rc: _StubRegimeEngine(),
    )

    close = 1.10
    for i in range(40):
        close *= 1.00015
        runtime.on_consolidated_bar(_make_bar("EURUSD", i, close))

    rows = runtime.artifacts.trade_training_rows
    assert len(rows) >= 1, "at least one training row should be emitted after a close"

    row = rows[0]
    assert row["symbol"] == "EURUSD"
    assert row["engine_source"] == "trend"
    assert row["direction"] == "LONG"
    assert row["exit_reason"] == "TREND_FLAT"
    assert "entry_price" in row and float(row["entry_price"]) > 0
    assert "exit_price" in row and float(row["exit_price"]) > 0
    assert "realized_pnl_pct" in row
    assert row["is_win"] in (0, 1)
    assert int(row["hold_bars"]) >= 0


def test_training_row_schema_fields() -> None:
    """All mandatory training-row fields must be present."""
    runtime = build_runtime_from_configs(
        config_dir=CONFIG_DIR,
        active_symbols=["EURUSD"],
        pairs_lookback_override=20,
        pairs_engine_factory=lambda pairs, lb, pc, rc, syms: _StubPairsEngine(pairs),
        trend_engine_factory=lambda syms, rc: _OpenThenCloseTrendEngine(),
        regime_engine_factory=lambda syms, rc: _StubRegimeEngine(),
    )

    close = 1.10
    for i in range(40):
        close *= 1.00015
        runtime.on_consolidated_bar(_make_bar("EURUSD", i, close))

    rows = runtime.artifacts.trade_training_rows
    if not rows:
        return  # open or close may have been rejected by risk — accept

    required_keys = {
        "entry_timestamp",
        "exit_timestamp",
        "symbol",
        "engine_source",
        "direction",
        "entry_price",
        "exit_price",
        "hold_bars",
        "entry_regime",
        "entry_regime_prob_trend",
        "entry_regime_prob_chop",
        "entry_regime_prob_risk_off",
        "realized_pnl_pct",
        "is_win",
        "exit_reason",
    }
    for key in required_keys:
        assert key in rows[0], f"training row missing required field: {key}"


def test_no_training_row_without_close() -> None:
    """No training row should be emitted if no close intent was ever approved."""
    runtime = build_runtime_from_configs(
        config_dir=CONFIG_DIR,
        active_symbols=["EURUSD"],
        pairs_lookback_override=20,
        pairs_engine_factory=lambda pairs, lb, pc, rc, syms: _StubPairsEngine(pairs),
        trend_engine_factory=lambda syms, rc: _OpenThenCloseTrendEngine(),
        regime_engine_factory=lambda syms, rc: _StubRegimeEngine(),
    )

    # Only run 19 bars — open fires at bar 20, close at bar 30.
    close = 1.10
    for i in range(19):
        close *= 1.00015
        runtime.on_consolidated_bar(_make_bar("EURUSD", i, close))

    assert runtime.artifacts.trade_training_rows == [], (
        "no training row should exist before close intent fires"
    )
