"""Paper/live persistence and health-state gating tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_lean_engine.orchestration.pipeline import build_runtime_from_configs
from fx_lean_engine.storage import LiveArtifactSink
from fx_lean_engine.types import Bar, RegimeState, TradeIntent, TrendSignal


class _PairsNoop:
    def __init__(self, pairs: list[tuple[str, str]]):
        self.pairs = list(pairs)

    def update(self, *_args, **_kwargs):
        return [], []


class _TrendAlwaysOpen:
    def __init__(self, symbols: list[str]):
        self.symbols = list(symbols)

    def update(self, snapshot: dict[str, float]):
        symbol = sorted(snapshot.keys())[0]
        return (
            [TrendSignal(symbol=symbol, p_up=0.8, p_down=0.2, confidence=0.6, direction="LONG")],
            [
                TradeIntent(
                    engine="trend",
                    action="open",
                    symbol=symbol,
                    pair=None,
                    direction="LONG",
                    notional_pct_nav=0.1,
                    confidence=0.6,
                    reason="HEALTH_TEST",
                )
            ],
        )


class _RegimeTrend:
    def update(self, *_args, **_kwargs):
        return RegimeState(
            state="TREND",
            p_trend=0.9,
            p_chop=0.1,
            p_risk_off=0.0,
            trend_weight=1.0,
            pairs_weight=0.0,
        )


def _pairs_factory(pair_tuples, _lookback, _pairs_cfg, _runtime_cfg, _active_symbols):
    return _PairsNoop(pair_tuples)


def _trend_factory(active_symbols, _runtime_cfg):
    return _TrendAlwaysOpen(active_symbols)


def _regime_factory(_active_symbols, _runtime_cfg):
    return _RegimeTrend()


def test_live_sink_append_only(tmp_path: Path) -> None:
    sink = LiveArtifactSink(tmp_path / "live", "run123")
    ts = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    sink.append_parquet_rows("signals", [{"timestamp": ts.isoformat(), "x": 1}])
    sink.append_parquet_rows("signals", [{"timestamp": ts.isoformat(), "x": 2}])

    parquet_path = tmp_path / "live" / "2026-01-01" / "run123" / "signals.parquet"
    frame = pd.read_parquet(parquet_path)
    assert frame.shape[0] == 2

    sink.append_jsonl_rows("broker_events", [{"timestamp": ts.isoformat(), "event": "A"}])
    sink.append_jsonl_rows("broker_events", [{"timestamp": ts.isoformat(), "event": "B"}])
    jsonl_path = tmp_path / "live" / "2026-01-01" / "run123" / "broker_events.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_broker_down_blocks_new_entries(tmp_path: Path) -> None:
    config_dir = Path(__file__).resolve().parents[1] / "configs"
    runtime = build_runtime_from_configs(
        config_dir=config_dir,
        active_symbols=["EURUSD"],
        pairs_lookback_override=30,
        pairs_engine_factory=_pairs_factory,
        trend_engine_factory=_trend_factory,
        regime_engine_factory=_regime_factory,
    )

    start = datetime(2025, 1, 1, tzinfo=UTC)
    close = 1.0
    for i in range(60):
        close *= 1.0003
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

    approved_before = [
        row for row in runtime.artifacts.orders if row.get("status") == "approved" and row.get("action") == "open"
    ]
    assert approved_before

    runtime.set_broker_health(True, "BROKER_TEST_DOWN", timestamp=start + timedelta(hours=20))

    for i in range(60, 70):
        close *= 1.0003
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

    blocked = [
        row
        for row in runtime.artifacts.orders
        if row.get("status") == "rejected" and str(row.get("risk_reason", "")).startswith("HEALTH_STATE_")
    ]
    assert blocked
    assert any(str(row.get("reason")) == "HEALTH_STATE_BROKER_DOWN" for row in runtime.artifacts.risk_events)
