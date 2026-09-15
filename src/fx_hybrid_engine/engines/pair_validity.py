"""Pair validity state machine for tradable/watch/disabled gating."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

PairState = Literal["TRADABLE", "WATCH", "DISABLED"]


@dataclass(slots=True)
class PairValiditySnapshot:
    pair_id: str
    status: PairState = "WATCH"
    disabled_until_scan: int | None = None
    high_pvalue_streak: int = 0
    last_pvalue: float | None = None
    last_beta: float | None = None
    median_spread_std: float | None = None
    last_reason: str = "initial"


@dataclass(slots=True)
class PairValidityManager:
    """State machine implementing tradable pair hysteresis and disable cooldown."""

    p_enter: float
    p_exit: float
    p_break: float
    p_recover: float
    break_scans_required: int
    spread_std_spike_k: float
    beta_jump_abs: float
    cooldown_scans: int
    entry_zscore: float
    snapshots: dict[str, PairValiditySnapshot] = field(default_factory=dict)
    events: list[dict[str, object]] = field(default_factory=list)
    _spread_history: dict[str, list[float]] = field(default_factory=dict)

    def register_pairs(self, pair_ids: list[str]) -> None:
        for pair_id in pair_ids:
            if pair_id not in self.snapshots:
                self.snapshots[pair_id] = PairValiditySnapshot(pair_id=pair_id)
                self._spread_history[pair_id] = []

    def _transition(
        self,
        *,
        snapshot: PairValiditySnapshot,
        to_state: PairState,
        reason: str,
        scan_idx: int,
        timestamp: str,
        disabled_until_scan: int | None = None,
    ) -> None:
        from_state = snapshot.status
        if from_state == to_state and snapshot.disabled_until_scan == disabled_until_scan:
            snapshot.last_reason = reason
            return
        snapshot.status = to_state
        snapshot.disabled_until_scan = disabled_until_scan
        snapshot.last_reason = reason
        self.events.append(
            {
                "timestamp": timestamp,
                "scan_idx": scan_idx,
                "pair_id": snapshot.pair_id,
                "from_state": from_state,
                "to_state": to_state,
                "reason": reason,
                "disabled_until_scan": disabled_until_scan,
            }
        )

    def apply_scan(self, scan_df: pd.DataFrame) -> None:
        """Apply one scan batch and mutate pair states."""
        if scan_df.empty:
            return
        work = scan_df.sort_values(["scan_idx", "pair_id"]).copy()
        for row in work.itertuples(index=False):
            pair_id = str(row.pair_id)
            scan_idx = int(row.scan_idx)
            timestamp = str(row.timestamp)
            pvalue = float(row.pvalue) if not pd.isna(row.pvalue) else np.nan
            beta = float(row.beta) if not pd.isna(row.beta) else np.nan
            spread_std = float(row.spread_std) if not pd.isna(row.spread_std) else np.nan
            z_abs_p95 = float(row.z_abs_p95) if not pd.isna(row.z_abs_p95) else np.nan

            self.register_pairs([pair_id])
            snap = self.snapshots[pair_id]
            history = self._spread_history[pair_id]

            if np.isnan(pvalue):
                self._transition(
                    snapshot=snap,
                    to_state="WATCH",
                    reason="missing_scan_metrics",
                    scan_idx=scan_idx,
                    timestamp=timestamp,
                )
                continue

            # Disabled cooldown handling.
            if snap.status == "DISABLED" and snap.disabled_until_scan is not None and scan_idx < snap.disabled_until_scan:
                snap.last_pvalue = pvalue
                snap.last_beta = None if np.isnan(beta) else beta
                if not np.isnan(spread_std):
                    history.append(spread_std)
                    snap.median_spread_std = float(np.median(history))
                continue
            if snap.status == "DISABLED" and snap.disabled_until_scan is not None and scan_idx >= snap.disabled_until_scan:
                self._transition(
                    snapshot=snap,
                    to_state="WATCH",
                    reason="cooldown_expired",
                    scan_idx=scan_idx,
                    timestamp=timestamp,
                    disabled_until_scan=None,
                )

            # Update p-value streak for breakdown trigger.
            if pvalue > self.p_break:
                snap.high_pvalue_streak += 1
            else:
                snap.high_pvalue_streak = 0

            # Breakdown triggers.
            breakdown_reason: str | None = None
            if snap.high_pvalue_streak >= self.break_scans_required:
                breakdown_reason = "pvalue_breakdown"

            if breakdown_reason is None and not np.isnan(spread_std):
                prev_median = float(np.median(history)) if history else spread_std
                if prev_median > 0 and spread_std > (self.spread_std_spike_k * prev_median):
                    breakdown_reason = "spread_std_spike"
            if breakdown_reason is None and snap.last_beta is not None and not np.isnan(beta):
                if abs(beta - snap.last_beta) > self.beta_jump_abs:
                    breakdown_reason = "beta_jump"

            # Update rolling metrics.
            if not np.isnan(spread_std):
                history.append(spread_std)
                snap.median_spread_std = float(np.median(history))
            snap.last_pvalue = pvalue
            snap.last_beta = None if np.isnan(beta) else beta

            if breakdown_reason is not None:
                self._transition(
                    snapshot=snap,
                    to_state="DISABLED",
                    reason=breakdown_reason,
                    scan_idx=scan_idx,
                    timestamp=timestamp,
                    disabled_until_scan=scan_idx + self.cooldown_scans,
                )
                continue

            # Hysteresis entry/exit/recovery.
            if snap.status == "WATCH":
                tradable_gate = (pvalue <= self.p_enter) and (not np.isnan(z_abs_p95)) and (z_abs_p95 >= self.entry_zscore)
                recovery_gate = (pvalue <= self.p_recover) and (not np.isnan(z_abs_p95)) and (z_abs_p95 >= self.entry_zscore)
                if tradable_gate or recovery_gate:
                    reason = "watch_to_tradable" if tradable_gate else "recovered_to_tradable"
                    self._transition(
                        snapshot=snap,
                        to_state="TRADABLE",
                        reason=reason,
                        scan_idx=scan_idx,
                        timestamp=timestamp,
                    )
            elif snap.status == "TRADABLE":
                if pvalue > self.p_exit:
                    self._transition(
                        snapshot=snap,
                        to_state="WATCH",
                        reason="pvalue_exit",
                        scan_idx=scan_idx,
                        timestamp=timestamp,
                    )

    def state_for_pair(self, pair_id: str) -> PairState:
        snap = self.snapshots.get(pair_id)
        if snap is None:
            return "WATCH"
        return snap.status

    def state_map(self) -> dict[str, PairState]:
        return {pair_id: snap.status for pair_id, snap in self.snapshots.items()}

    def events_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            self.events,
            columns=[
                "timestamp",
                "scan_idx",
                "pair_id",
                "from_state",
                "to_state",
                "reason",
                "disabled_until_scan",
            ],
        )

    def snapshot_payload(self) -> dict[str, dict[str, object]]:
        payload: dict[str, dict[str, object]] = {}
        for pair_id, snap in self.snapshots.items():
            payload[pair_id] = {
                "status": snap.status,
                "disabled_until_scan": snap.disabled_until_scan,
                "high_pvalue_streak": snap.high_pvalue_streak,
                "last_pvalue": snap.last_pvalue,
                "last_beta": snap.last_beta,
                "median_spread_std": snap.median_spread_std,
                "last_reason": snap.last_reason,
            }
        return payload
