"""Phase 1 Gate A tests: subscriptions and consolidation heartbeat."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fx_lean_engine.lean.algorithm import FxLeanEngineAlgorithm


@dataclass
class _Security:
    Symbol: str


@dataclass
class _TradeBar:
    Time: datetime
    EndTime: datetime
    Open: float
    High: float
    Low: float
    Close: float
    Volume: float


@dataclass
class _Slice:
    Bars: dict[str, _TradeBar]


class _Algo(FxLeanEngineAlgorithm):
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.errors: list[str] = []
        self.calls: list[tuple[str, object]] = []
        self.IsWarmingUp = False

    def AddForex(self, pair: str, resolution: object) -> _Security:  # noqa: N802
        self.calls.append((pair, resolution))
        return _Security(Symbol=pair)

    def Log(self, message: str) -> None:  # noqa: N802
        self.logs.append(message)

    def Error(self, message: str) -> None:  # noqa: N802
        self.errors.append(message)

    def SetStartDate(self, *_args, **_kwargs) -> None:  # noqa: N802
        return

    def SetEndDate(self, *_args, **_kwargs) -> None:  # noqa: N802
        return

    def SetCash(self, *_args, **_kwargs) -> None:  # noqa: N802
        return

    def SetWarmup(self, *_args, **_kwargs) -> None:  # noqa: N802
        return


def test_phase1_gate_a_subscription_logging_and_heartbeat(monkeypatch) -> None:
    monkeypatch.setenv("FXLE_BACKTEST_CONFIG", "backtest_phase1_verification.yaml")

    algo = _Algo()
    algo.Initialize()

    assert any("Subscribed:" in line for line in algo.logs)
    assert any("EURUSD" in line and "GBPUSD" in line and "USDJPY" in line for line in algo.logs)
    assert len(algo.calls) == 3

    start = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    symbols = ["EURUSD", "GBPUSD", "USDJPY"]

    for i in range(16):
        ts = start + timedelta(minutes=i)
        bars = {
            symbol: _TradeBar(
                Time=ts,
                EndTime=ts + timedelta(minutes=1),
                Open=1.0 + i * 0.0001,
                High=1.0005 + i * 0.0001,
                Low=0.9995 + i * 0.0001,
                Close=1.0 + i * 0.0002,
                Volume=1000.0,
            )
            for symbol in symbols
        }
        algo.OnData(_Slice(Bars=bars))

    heartbeat = [line for line in algo.logs if line.startswith("BAR_EMIT")]
    assert any("symbol=EURUSD" in line for line in heartbeat)
    assert any("symbol=GBPUSD" in line for line in heartbeat)
    assert any("symbol=USDJPY" in line for line in heartbeat)

    algo.OnWarmupFinished()
    assert any("WARMUP_DATA_OK" in line for line in algo.logs)
    assert not algo.errors
