"""Unit tests for close-only execution policy sanitizer."""
from __future__ import annotations

from fx_hybrid_engine.ops.execution_policy import apply_close_only_policy


def test_close_only_blocks_new_entries_and_flips():
    current = {"EURUSD": 0.0, "GBPUSD": 0.2, "USDJPY": -0.3}
    proposed = {"EURUSD": 0.1, "GBPUSD": -0.1, "USDJPY": -0.6}
    result = apply_close_only_policy(current, proposed, close_only=True)
    assert "EURUSD" not in result.sanitized_targets
    assert "GBPUSD" not in result.sanitized_targets
    assert result.sanitized_targets["USDJPY"] == -0.3
    reasons = {row["reason"] for row in result.blocked_actions}
    assert "new_entry_blocked" in reasons
    assert "flip_blocked_must_close_first" in reasons
    assert "size_increase_blocked" in reasons


def test_normal_mode_leaves_targets_unchanged():
    proposed = {"EURUSD": 0.1, "GBPUSD": -0.2}
    result = apply_close_only_policy({}, proposed, close_only=False)
    assert result.sanitized_targets == proposed
    assert result.blocked_actions == []

