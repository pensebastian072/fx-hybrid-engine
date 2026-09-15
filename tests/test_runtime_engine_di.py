"""Runtime builder dependency-injection tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_lean_engine.orchestration.pipeline import build_runtime_from_configs
from fx_lean_engine.types import Bar, RegimeState, TradeIntent, TrendSignal


class StubPairsEngine:
    def __init__(self, pairs: list[tuple[str, str]]):
        self.pairs = list(pairs)

    def update(self, *_args, **_kwargs):
        return [], []


class StubTrendEngine:
    def __init__(self, symbols: list[str]):
        self.symbols = list(symbols)

    def update(self, snapshot: dict[str, float]):
        symbol = sorted(snapshot.keys())[0]
        return (
            [TrendSignal(symbol=symbol, p_up=0.6, p_down=0.4, confidence=0.2, direction="LONG")],
            [
                TradeIntent(
                    engine="trend",
                    action="open",
                    symbol=symbol,
                    pair=None,
                    direction="LONG",
                    notional_pct_nav=0.05,
                    confidence=0.2,
                    reason="DI_TEST",
                )
            ],
        )


class StubRegimeEngine:
    def update(self, *_args, **_kwargs) -> RegimeState:
        return RegimeState(
            state="TREND",
            p_trend=0.8,
            p_chop=0.2,
            p_risk_off=0.0,
            trend_weight=1.0,
            pairs_weight=0.0,
        )


def pairs_factory(pair_tuples, _lookback, _pairs_cfg, _runtime_cfg, _active_symbols):
    return StubPairsEngine(pair_tuples)


def trend_factory(active_symbols, _runtime_cfg):
    return StubTrendEngine(active_symbols)


def regime_factory(_active_symbols, _runtime_cfg):
    return StubRegimeEngine()


def test_runtime_builder_supports_engine_di() -> None:
    config_dir = Path(__file__).resolve().parents[1] / "configs"
    runtime = build_runtime_from_configs(
        config_dir=config_dir,
        active_symbols=["EURUSD"],
        pairs_lookback_override=30,
        pairs_engine_factory=pairs_factory,
        trend_engine_factory=trend_factory,
        regime_engine_factory=regime_factory,
    )

    assert isinstance(runtime.pairs_engine, StubPairsEngine)
    assert isinstance(runtime.trend_engine, StubTrendEngine)
    assert isinstance(runtime.regime_orchestrator, StubRegimeEngine)

    start = datetime(2025, 1, 1, tzinfo=UTC)
    close = 1.0
    for i in range(60):
        close *= 1.0002
        runtime.on_consolidated_bar(
            Bar(
                symbol="EURUSD",
                start=start + timedelta(minutes=15 * i),
                end=start + timedelta(minutes=15 * (i + 1)),
                open=close * 0.999,
                high=close * 1.001,
                low=close * 0.998,
                close=close,
                volume=1000.0,
            )
        )

    assert any(row.get("reason") == "DI_TEST" for row in runtime.artifacts.orders)
