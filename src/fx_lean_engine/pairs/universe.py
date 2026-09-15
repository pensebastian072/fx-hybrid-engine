"""Candidate pair generation for Phase 2."""

from __future__ import annotations

from itertools import combinations

from fx_lean_engine.config.models import PairsPolicyConfig


def _normalize_pair(left: str, right: str) -> tuple[str, str]:
    a = str(left).upper().replace("/", "").strip()
    b = str(right).upper().replace("/", "").strip()
    return (a, b) if a <= b else (b, a)


def generate_candidate_pairs(policy: PairsPolicyConfig, available_symbols: list[str]) -> tuple[list[tuple[str, str]], list[dict[str, str]]]:
    """Build deterministic candidate pair list and eligibility rows."""
    available = {str(symbol).upper().replace("/", "").strip() for symbol in available_symbols}

    candidate_set: set[tuple[str, str]] = set()
    for pair in policy.pairs or []:
        candidate_set.add(_normalize_pair(pair[0], pair[1]))

    for _, symbols in (policy.groups or {}).items():
        clean = [str(symbol).upper().replace("/", "").strip() for symbol in symbols]
        for left, right in combinations(clean, 2):
            candidate_set.add(_normalize_pair(left, right))

    avoid = {_normalize_pair(pair[0], pair[1]) for pair in policy.avoid_pairs or []}

    rows: list[dict[str, str]] = []
    eligible: list[tuple[str, str]] = []
    for left, right in sorted(candidate_set):
        pair = (left, right)
        reason = "eligible"
        status = "eligible"
        if pair in avoid:
            reason = "avoid_list"
            status = "excluded"
        elif left not in available or right not in available:
            reason = "insufficient_data"
            status = "excluded"
        else:
            eligible.append(pair)

        rows.append(
            {
                "pair": f"{left}-{right}",
                "left": left,
                "right": right,
                "status": status,
                "reason": reason,
            }
        )

    return eligible, rows
