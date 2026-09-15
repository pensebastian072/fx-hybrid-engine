"""Execution policy sanitizers for close-only risk states."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PolicyResult:
    sanitized_targets: dict[str, float]
    blocked_actions: list[dict[str, object]]


def _sign(x: float, eps: float = 1e-12) -> int:
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


def apply_close_only_policy(
    current_weights: dict[str, float],
    proposed_targets: dict[str, float],
    *,
    close_only: bool,
) -> PolicyResult:
    if not close_only:
        return PolicyResult(dict(proposed_targets), [])

    out: dict[str, float] = {}
    blocked: list[dict[str, object]] = []
    for symbol in sorted(set(current_weights.keys()) | set(proposed_targets.keys())):
        curr = float(current_weights.get(symbol, 0.0))
        proposed = float(proposed_targets.get(symbol, 0.0))
        curr_sign = _sign(curr)
        prop_sign = _sign(proposed)

        allowed = proposed
        reason: str | None = None
        if curr_sign == 0 and prop_sign != 0:
            allowed = 0.0
            reason = "new_entry_blocked"
        elif curr_sign != 0 and prop_sign != 0 and curr_sign != prop_sign:
            allowed = 0.0
            reason = "flip_blocked_must_close_first"
        elif curr_sign != 0 and prop_sign == curr_sign and abs(proposed) > abs(curr):
            allowed = curr
            reason = "size_increase_blocked"

        out[symbol] = allowed
        if reason is not None:
            blocked.append(
                {
                    "symbol": symbol,
                    "reason": reason,
                    "current_weight": curr,
                    "proposed_target": proposed,
                    "sanitized_target": allowed,
                }
            )

    # Keep output compact by dropping exact zero symbols.
    compact = {k: v for k, v in out.items() if abs(v) > 1e-12}
    return PolicyResult(compact, blocked)

