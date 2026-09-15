"""Unit tests for deterministic identity helpers."""
from __future__ import annotations

from datetime import UTC, datetime

from fx_hybrid_engine.utils.identity import hash_config, make_run_id


def test_hash_config_is_key_order_independent():
    a = {"x": 1, "nested": {"b": 2, "a": 1}}
    b = {"nested": {"a": 1, "b": 2}, "x": 1}
    assert hash_config(a) == hash_config(b)


def test_make_run_id_is_deterministic_for_fixed_inputs():
    ts = datetime(2026, 2, 27, 12, 0, 0, tzinfo=UTC)
    config_hash = "abc12345" + ("0" * 56)
    rid = make_run_id(ts, config_hash)
    assert rid == "20260227_120000_abc12345"
