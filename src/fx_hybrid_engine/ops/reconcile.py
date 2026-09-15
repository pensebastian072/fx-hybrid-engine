"""Reconciliation helpers for holdings/order mismatches and escalation actions."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ReconcileResult:
    holdings_match: bool
    orders_match: bool
    pause_entries: bool
    attempt_reconcile: bool
    flatten_required: bool
    missing_symbols: list[str]
    extra_symbols: list[str]
    quantity_mismatches: list[dict[str, float]]
    missing_order_ids: list[str]
    extra_order_ids: list[str]


def reconcile_holdings(
    expected: Mapping[str, float],
    actual: Mapping[str, float],
    tolerance: float = 1e-8,
) -> tuple[list[str], list[str], list[dict[str, float]]]:
    expected_keys = set(expected.keys())
    actual_keys = set(actual.keys())
    missing = sorted(expected_keys - actual_keys)
    extra = sorted(actual_keys - expected_keys)
    mismatches: list[dict[str, float]] = []

    for symbol in sorted(expected_keys & actual_keys):
        exp = float(expected[symbol])
        act = float(actual[symbol])
        if abs(exp - act) > tolerance:
            mismatches.append(
                {
                    "symbol": symbol,
                    "expected_qty": exp,
                    "actual_qty": act,
                }
            )
    return missing, extra, mismatches


def reconcile_open_orders(
    expected_order_ids: set[str],
    actual_order_ids: set[str],
) -> tuple[list[str], list[str]]:
    missing = sorted(expected_order_ids - actual_order_ids)
    extra = sorted(actual_order_ids - expected_order_ids)
    return missing, extra


def evaluate_reconciliation(
    expected_holdings: Mapping[str, float],
    actual_holdings: Mapping[str, float],
    expected_order_ids: set[str],
    actual_order_ids: set[str],
    tolerance: float = 1e-8,
    *,
    mismatch_cycles: int = 1,
    persistent_mismatch_cycles: int = 3,
    auto_flatten_on_persistent_mismatch: bool = False,
) -> ReconcileResult:
    missing_symbols, extra_symbols, qty_mismatches = reconcile_holdings(
        expected_holdings,
        actual_holdings,
        tolerance=tolerance,
    )
    missing_orders, extra_orders = reconcile_open_orders(expected_order_ids, actual_order_ids)
    holdings_match = len(missing_symbols) == 0 and len(extra_symbols) == 0 and len(qty_mismatches) == 0
    orders_match = len(missing_orders) == 0 and len(extra_orders) == 0
    pause_entries = not (holdings_match and orders_match)
    attempt_reconcile = pause_entries
    flatten_required = (
        pause_entries
        and auto_flatten_on_persistent_mismatch
        and int(mismatch_cycles) >= int(persistent_mismatch_cycles)
    )
    return ReconcileResult(
        holdings_match=holdings_match,
        orders_match=orders_match,
        pause_entries=pause_entries,
        attempt_reconcile=attempt_reconcile,
        flatten_required=flatten_required,
        missing_symbols=missing_symbols,
        extra_symbols=extra_symbols,
        quantity_mismatches=qty_mismatches,
        missing_order_ids=missing_orders,
        extra_order_ids=extra_orders,
    )

