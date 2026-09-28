"""Minute-bar consolidation router."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from fx_lean_engine.types import Bar


def _floor_to_interval(ts: datetime, interval_minutes: int) -> datetime:
    """Return the start of the interval-minute window that contains ts."""
    total_minutes = ts.hour * 60 + ts.minute
    floored = (total_minutes // interval_minutes) * interval_minutes
    return ts.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)


class BarRouter:
    """Aggregate minute bars into consolidated N-minute bars."""

    def __init__(self, interval_minutes: int = 15) -> None:
        self._interval = int(interval_minutes)
        self._callbacks: dict[str, list[Callable[[Bar], Any]]] = defaultdict(list)
        self._buffers: dict[str, list[Bar]] = {}
        self._window_ends: dict[str, datetime] = {}

    def register(self, symbol: str, callback: Callable[[Bar], Any]) -> None:
        """Register a callback to receive consolidated bars for *symbol*."""
        key = str(symbol).upper().strip()
        self._callbacks[key].append(callback)
        if key not in self._buffers:
            self._buffers[key] = []

    def on_minute_bar(self, bar: Bar) -> None:
        """Feed one minute bar; emit a consolidated bar when an interval is complete."""
        key = str(bar.symbol).upper().strip()
        if key not in self._callbacks:
            return

        buf = self._buffers.setdefault(key, [])
        win_end = self._window_ends.get(key)

        if win_end is None:
            win_start = _floor_to_interval(bar.start, self._interval)
            self._window_ends[key] = win_start + timedelta(minutes=self._interval)
            buf.append(bar)
            return

        if bar.start >= win_end:
            if buf:
                self._emit(key, buf, win_end)
            new_win_start = _floor_to_interval(bar.start, self._interval)
            self._window_ends[key] = new_win_start + timedelta(minutes=self._interval)
            self._buffers[key] = [bar]
        else:
            buf.append(bar)

    def _emit(self, key: str, buf: list[Bar], win_end: datetime) -> None:
        open_px = float(buf[0].open)
        high_px = max(float(b.high) for b in buf)
        low_px = min(float(b.low) for b in buf)
        close_px = float(buf[-1].close)
        volume = sum(float(b.volume) for b in buf)
        win_start = buf[0].start

        consolidated = Bar(
            symbol=buf[0].symbol,
            start=win_start,
            end=win_end,
            open=open_px,
            high=high_px,
            low=low_px,
            close=close_px,
            volume=volume,
        )
        for cb in self._callbacks[key]:
            cb(consolidated)
