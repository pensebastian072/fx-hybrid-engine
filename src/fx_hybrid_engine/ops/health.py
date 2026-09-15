"""Operational health checks and state machine for close-only control."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DATA_OK = "DATA_OK"
DATA_STALE = "DATA_STALE"
BROKER_DOWN = "BROKER_DOWN"
DEGRADED = "DEGRADED"


@dataclass(frozen=True)
class HealthPolicy:
    data_stale_seconds: int = 300
    degraded_rejects: int = 3
    broker_down_rejects: int = 8
    max_missing_bars: int = 1


def _to_utc(ts: object) -> pd.Timestamp:
    out = pd.Timestamp(ts)
    if out.tzinfo is None:
        return out.tz_localize("UTC")
    return out.tz_convert("UTC")


def is_bar_stale(
    now_utc: object,
    last_bar_timestamp_utc: object | None,
    max_bar_staleness_seconds: int,
) -> bool:
    if last_bar_timestamp_utc is None:
        return True
    now = _to_utc(now_utc)
    last = _to_utc(last_bar_timestamp_utc)
    age = (now - last).total_seconds()
    return age > float(max_bar_staleness_seconds)


def evaluate_health(
    now_utc: object,
    last_bar_timestamp_utc: object | None,
    consecutive_rejects: int,
    policy: HealthPolicy,
    *,
    missing_bars: int = 0,
    broker_connected: bool = True,
) -> dict[str, object]:
    stale = is_bar_stale(now_utc, last_bar_timestamp_utc, policy.data_stale_seconds)
    reasons: list[str] = []

    if not broker_connected:
        reasons.append("broker_disconnected")
    if int(consecutive_rejects) >= int(policy.broker_down_rejects):
        reasons.append("broker_reject_threshold")
    if stale:
        reasons.append("stale_data")
    if int(missing_bars) > int(policy.max_missing_bars):
        reasons.append("missing_bars")
    if int(consecutive_rejects) >= int(policy.degraded_rejects):
        reasons.append("rejects_degraded")

    if "broker_disconnected" in reasons or "broker_reject_threshold" in reasons:
        state = BROKER_DOWN
        close_only = True
    elif stale:
        state = DATA_STALE
        close_only = True
    elif "missing_bars" in reasons or "rejects_degraded" in reasons:
        state = DEGRADED
        close_only = True
    else:
        state = DATA_OK
        close_only = False

    return {
        "state": state,
        "healthy": state == DATA_OK,
        "close_only": close_only,
        "reasons": reasons,
    }

