"""Unit tests for build_trade_analytics_rows() from realized fills (Task 5)."""

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
            p_trend=0.7,
            p_chop=0.2,
            p_risk_off=0.1,
            trend_weight=1.0,
            pairs_weight=0.5,
        )


class _StubPairsEngine:
    def __init__(self, pairs):
        self.pairs = list(pairs)

    def update(self, *_a, **_kw):
        return [], []


class _ScriptedTrendEngine:
    """Opens LONG at bar 15, closes at bar 25 (profitable uptrend), re-opens at 35."""

    _bar = 0
    _pos: str | None = None

    def update(self, snapshot: dict[str, float]):
        self._bar += 1
        sym = sorted(snapshot.keys())[0]

        if self._bar == 15 and self._pos is None:
            self._pos = "LONG"
            return (
                [TrendSignal(sym, 0.7, 0.3, 0.4, "LONG")],
                [TradeIntent("trend", "open", sym, None, "LONG", 0.05, 0.4, "TREND_SIGNAL")],
            )
        if self._bar == 25 and self._pos == "LONG":
            self._pos = None
            return (
                [TrendSignal(sym, 0.5, 0.5, 0.0, "FLAT")],
                [TradeIntent("trend", "close", sym, None, "EXIT", 0.05, 0.0, "TREND_FLAT")],
            )
        if self._bar == 35 and self._pos is None:
            self._pos = "SHORT"
            return (
                [TrendSignal(sym, 0.3, 0.7, 0.4, "SHORT")],
                [TradeIntent("trend", "open", sym, None, "SHORT", 0.05, 0.4, "TREND_SIGNAL")],
            )
        if self._bar == 45 and self._pos == "SHORT":
            self._pos = None
            return (
                [TrendSignal(sym, 0.5, 0.5, 0.0, "FLAT")],
                [TradeIntent("trend", "close", sym, None, "EXIT", 0.05, 0.0, "TREND_FLAT")],
            )
        return [TrendSignal(sym, 0.5, 0.5, 0.0, "FLAT")], []


def _make_bar(symbol: str, i: int, close: float) -> Bar:
    return Bar(
        symbol=symbol,
        start=_T0 + timedelta(minutes=15 * i),
        end=_T0 + timedelta(minutes=15 * (i + 1)),
        open=close * 0.9998,
        high=close * 1.002,
        low=close * 0.998,
        close=close,
        volume=1000.0,
    )


def _build_runtime(engine_factory=None):
    return build_runtime_from_configs(
        config_dir=CONFIG_DIR,
        active_symbols=["EURUSD"],
        pairs_lookback_override=20,
        pairs_engine_factory=lambda pairs, lb, pc, rc, syms: _StubPairsEngine(pairs),
        trend_engine_factory=engine_factory or (lambda syms, rc: _ScriptedTrendEngine()),
        regime_engine_factory=lambda syms, rc: _StubRegimeEngine(),
    )


def test_build_trade_analytics_returns_rows() -> None:
    """build_trade_analytics_rows must return at least one row after a complete trade."""
    runtime = _build_runtime()
    close = 1.10
    for i in range(50):
        close *= 1.00020  # gentle uptrend so entry ≠ exit
        runtime.on_consolidated_bar(_make_bar("EURUSD", i, close))

    rows = runtime.build_trade_analytics_rows()
    assert len(rows) >= 1, "expected at least one completed round-trip trade"


def test_trade_analytics_row_schema() -> None:
    """Each analytics row must contain all required keys with sensible types."""
    runtime = _build_runtime()
    close = 1.10
    for i in range(50):
        close *= 1.00020
        runtime.on_consolidated_bar(_make_bar("EURUSD", i, close))

    rows = runtime.build_trade_analytics_rows()
    if not rows:
        return  # no completed trades (risk rejected) — skip

    required = {
        "entry_timestamp", "exit_timestamp", "symbol", "engine_source", "direction",
        "entry_price", "exit_price", "mfe", "mae", "entry_efficiency",
        "realized_pnl_pct", "is_win", "exit_reason", "hold_bars",
    }
    for key in required:
        assert key in rows[0], f"analytics row missing field: {key}"

    for row in rows:
        assert row["is_win"] in (0, 1)
        assert float(row["mfe"]) >= 0.0
        assert float(row["mae"]) >= 0.0
        assert 0.0 <= float(row["entry_efficiency"]) <= 1.0
        assert int(row["hold_bars"]) >= 0


def test_trade_analytics_sets_artifacts() -> None:
    """build_trade_analytics_rows must also populate artifacts.trade_analytics."""
    runtime = _build_runtime()
    close = 1.10
    for i in range(50):
        close *= 1.00020
        runtime.on_consolidated_bar(_make_bar("EURUSD", i, close))

    rows = runtime.build_trade_analytics_rows()
    assert runtime.artifacts.trade_analytics is rows


def test_build_metrics_includes_analytics_keys() -> None:
    """build_metrics must include win_rate, entry_efficiency and related analytics keys."""
    runtime = _build_runtime()
    close = 1.10
    for i in range(50):
        close *= 1.00020
        runtime.on_consolidated_bar(_make_bar("EURUSD", i, close))

    metrics = runtime.build_metrics(
        run_id="test",
        start="2025-01-01",
        end="2025-06-01",
        resolution="15min",
    )
    for key in (
        "trade_analytics_rows",
        "win_rate",
        "average_adverse_excursion",
        "entry_efficiency",
        "win_rate_by_signal_type",
        "exit_reason_distribution",
        "trade_attribution",
    ):
        assert key in metrics, f"metrics.json missing analytics key: {key}"


def test_empty_bars_gives_zero_analytics() -> None:
    """With no bars processed, analytics should be empty and not crash."""
    runtime = _build_runtime()
    rows = runtime.build_trade_analytics_rows()
    assert rows == []
    metrics = runtime.build_metrics(
        run_id="empty",
        start="2025-01-01",
        end="2025-06-01",
        resolution="15min",
    )
    assert metrics["trade_analytics_rows"] == 0
    assert metrics["win_rate"] == 0.0
