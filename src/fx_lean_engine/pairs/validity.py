"""Tradability state transitions for pairs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta

import numpy as np

from fx_lean_engine.config.models import PairsPolicyConfig
from fx_lean_engine.types import PairFitResult, PairStatus, PairValidityState


def evaluate_pair_validity(
    fit: PairFitResult,
    previous_state: PairValidityState,
    policy: PairsPolicyConfig,
    cooldown_delta: timedelta,
) -> tuple[PairValidityState, list[dict[str, str]]]:
    """Evaluate one scan row and return updated state + transition events."""
    state = previous_state
    state.scans_total += 1
    state.pval_history.append(float(fit.p_value))
    state.spread_std_history.append(float(fit.spread_std))
    state.beta_prev = float(fit.beta)

    events: list[dict[str, str]] = []
    now = fit.timestamp

    spread_hist = np.asarray(state.spread_std_history, dtype=float)
    spread_med = float(np.median(spread_hist)) if spread_hist.size > 0 else float(fit.spread_std)
    variance_break = float(fit.spread_std) > policy.variance_break_mult * max(spread_med, 1e-12)
    beta_break = float(fit.beta_drift) > policy.beta_jump_threshold

    if fit.p_value > policy.p_break or variance_break or beta_break:
        state.break_scans += 1
    else:
        state.break_scans = 0

    if state.status == PairStatus.DISABLED:
        if state.disabled_until is not None and now < state.disabled_until:
            state.status_reason = "COOLDOWN_ACTIVE"
            return state, events

        if fit.p_value < policy.p_recover:
            state.pass_scans += 1
            if state.pass_scans >= policy.recover_scans_required:
                prev = state.status
                state.status = PairStatus.TRADABLE
                state.status_reason = "RECOVERED"
                state.last_pass_time = now
                state.fail_scans = 0
                state.break_scans = 0
                events.append(
                    {
                        "timestamp": now.isoformat(),
                        "pair": f"{fit.pair[0]}-{fit.pair[1]}",
                        "event": "STATUS_CHANGE",
                        "from": str(prev),
                        "to": str(state.status),
                        "reason": state.status_reason,
                    }
                )
        else:
            state.pass_scans = 0
        return state, events

    if state.break_scans >= policy.break_scans_required:
        prev = state.status
        state.status = PairStatus.DISABLED
        state.status_reason = "BREAKDOWN"
        state.disabled_until = now + cooldown_delta
        state.last_fail_time = now
        state.pass_scans = 0
        state.fail_scans += 1
        events.append(
            {
                "timestamp": now.isoformat(),
                "pair": f"{fit.pair[0]}-{fit.pair[1]}",
                "event": "STATUS_CHANGE",
                "from": str(prev),
                "to": str(state.status),
                "reason": state.status_reason,
            }
        )
        return state, events

    if fit.p_value < policy.p_enter:
        prev = state.status
        state.status = PairStatus.TRADABLE
        state.status_reason = "P_ENTER"
        state.last_pass_time = now
        state.pass_scans += 1
        state.fail_scans = 0
        if prev != state.status:
            events.append(
                {
                    "timestamp": now.isoformat(),
                    "pair": f"{fit.pair[0]}-{fit.pair[1]}",
                    "event": "STATUS_CHANGE",
                    "from": str(prev),
                    "to": str(state.status),
                    "reason": state.status_reason,
                }
            )
    elif fit.p_value > policy.p_exit:
        prev = state.status
        state.status = PairStatus.WATCH
        state.status_reason = "P_EXIT"
        state.last_fail_time = now
        state.fail_scans += 1
        state.pass_scans = 0
        if prev != state.status:
            events.append(
                {
                    "timestamp": now.isoformat(),
                    "pair": f"{fit.pair[0]}-{fit.pair[1]}",
                    "event": "STATUS_CHANGE",
                    "from": str(prev),
                    "to": str(state.status),
                    "reason": state.status_reason,
                }
            )

    return state, events


class PairValidityManager:
    """Maintains pair tradability states across scans."""

    def __init__(self, policy: PairsPolicyConfig, bar_interval_minutes: int):
        self.policy = policy
        self.bar_interval_minutes = max(int(bar_interval_minutes), 1)
        self.states: dict[tuple[str, str], PairValidityState] = {}

    def _cooldown_delta(self) -> timedelta:
        cooldown_minutes = self.policy.disable_cooldown_bars * self.bar_interval_minutes
        return timedelta(minutes=cooldown_minutes)

    def get_status_map(self) -> dict[tuple[str, str], str]:
        """Return current pair status lookup."""
        return {pair: str(state.status) for pair, state in self.states.items()}

    def apply_scan(self, fits: list[PairFitResult]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """Apply scan results and return (scan_rows, transition_events)."""
        scan_rows: list[dict[str, str]] = []
        events: list[dict[str, str]] = []
        cooldown_delta = self._cooldown_delta()

        for fit in fits:
            pair = (fit.pair[0], fit.pair[1])
            previous = self.states.get(pair)
            if previous is None:
                previous = PairValidityState(pair=pair)

            updated, updates = evaluate_pair_validity(fit, previous, self.policy, cooldown_delta)
            self.states[pair] = updated
            events.extend(updates)

            scan_rows.append(
                {
                    "timestamp": fit.timestamp.isoformat(),
                    "pair": f"{pair[0]}-{pair[1]}",
                    "beta": f"{fit.beta:.8f}",
                    "p_value": f"{fit.p_value:.8f}",
                    "spread_std": f"{fit.spread_std:.8f}",
                    "half_life": f"{fit.half_life:.8f}",
                    "beta_drift": f"{fit.beta_drift:.8f}",
                    "spread_last_z": f"{fit.spread_last_z:.8f}",
                    "pair_status": str(updated.status),
                    "status_reason": updated.status_reason,
                    "disabled_until": updated.disabled_until.isoformat() if updated.disabled_until else "",
                }
            )

        return scan_rows, events

    def force_disable(self, pair: tuple[str, str], timestamp: datetime, reason: str) -> list[dict[str, str]]:
        """Force-disable one pair for cooldown window."""
        key = (str(pair[0]).upper().strip(), str(pair[1]).upper().strip())
        state = self.states.get(key)
        if state is None:
            state = PairValidityState(pair=key)

        prev = state.status
        state.status = PairStatus.DISABLED
        state.status_reason = str(reason).strip() or "FORCED_DISABLE"
        state.disabled_until = timestamp + self._cooldown_delta()
        state.last_fail_time = timestamp
        state.break_scans = max(int(state.break_scans), int(self.policy.break_scans_required))
        self.states[key] = state

        if prev == PairStatus.DISABLED:
            return []

        return [
            {
                "timestamp": timestamp.isoformat(),
                "pair": f"{key[0]}-{key[1]}",
                "event": "STATUS_CHANGE",
                "from": str(prev),
                "to": str(PairStatus.DISABLED),
                "reason": state.status_reason,
            }
        ]

    def state_rows(self) -> list[dict[str, str]]:
        """Serialize current states for debugging/reporting."""
        rows: list[dict[str, str]] = []
        for pair, state in sorted(self.states.items()):
            payload = asdict(state)
            payload["pair"] = f"{pair[0]}-{pair[1]}"
            payload["status"] = str(state.status)
            payload["last_pass_time"] = state.last_pass_time.isoformat() if state.last_pass_time else ""
            payload["last_fail_time"] = state.last_fail_time.isoformat() if state.last_fail_time else ""
            payload["disabled_until"] = state.disabled_until.isoformat() if state.disabled_until else ""
            payload["pval_history"] = ";".join(f"{value:.6f}" for value in state.pval_history or [])
            payload["spread_std_history"] = ";".join(f"{value:.6f}" for value in state.spread_std_history or [])
            rows.append({key: str(value) for key, value in payload.items() if key != "pair"})
            rows[-1]["pair"] = f"{pair[0]}-{pair[1]}"
        return rows
