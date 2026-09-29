"""Bar-level health checker for gap and ordering integrity."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fx_lean_engine.types import BarHealthEvent


class BarHealthChecker:
    """Track bar ordering and gap health per symbol."""

    def __init__(
        self,
        bar_interval_minutes: int = 15,
        gap_warn_threshold_minutes: float = 30.0,
        strict_bar_ordering: bool = True,
    ) -> None:
        self._interval = int(bar_interval_minutes)
        self._gap_threshold = float(gap_warn_threshold_minutes)
        self._strict = bool(strict_bar_ordering)
        self._last_timestamps: dict[str, datetime] = {}

    def check(self, symbol: str, timestamp: datetime) -> tuple[bool, list[BarHealthEvent]]:
        """Check health of a bar for *symbol* arriving at *timestamp*.

        Returns *(accept, events)* where *accept=False* drops the bar.
        """
        key = str(symbol).upper().strip()
        ts = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
        events: list[BarHealthEvent] = []
        accept = True

        last = self._last_timestamps.get(key)
        if last is not None:
            if ts <= last:
                events.append(
                    BarHealthEvent(
                        symbol=key,
                        timestamp=ts,
                        event_type="DUPLICATE_TIMESTAMP",
                        detail=f"ts={ts.isoformat()} last={last.isoformat()}",
                        severity="warn",
                    )
                )
                if self._strict:
                    accept = False
            else:
                gap_minutes = (ts - last).total_seconds() / 60.0
                expected_gap = float(self._interval)
                if gap_minutes > self._gap_threshold:
                    missing = int((gap_minutes - expected_gap) / expected_gap)
                    events.append(
                        BarHealthEvent(
                            symbol=key,
                            timestamp=ts,
                            event_type="MISSING_BAR_GAP",
                            detail=f"gap_minutes={gap_minutes:.1f} expected={expected_gap:.1f} missing_bars={missing}",
                            severity="warn",
                        )
                    )

        if accept:
            self._last_timestamps[key] = ts

        return accept, events

    def snapshot_last_timestamps(self) -> dict[str, datetime]:
        """Return the latest accepted timestamp per symbol."""
        return dict(self._last_timestamps)

    @staticmethod
    def event_row(event: BarHealthEvent) -> dict[str, Any]:
        """Convert a BarHealthEvent to a serialisable row dict."""
        row = asdict(event)
        row["timestamp"] = event.timestamp.isoformat()
        return row
