"""Unit tests for risk/controls.py and risk/position_sizing.py."""
from __future__ import annotations
import pytest

from fx_hybrid_engine.risk.controls import RiskController
from fx_hybrid_engine.risk.position_sizing import vol_target_scalar, size_pairs_legs
from fx_hybrid_engine.utils.config import RiskConfig


def _cfg() -> RiskConfig:
    return RiskConfig(max_leverage=3.0, stop_loss_pct=0.02, drawdown_kill_pct=0.05, vol_target_annual=0.15)


def test_kill_switch_triggers_on_drawdown():
    cfg = _cfg()
    ctrl = RiskController(cfg, initial_equity=100.0)
    assert not ctrl.in_safe_mode
    # Simulate 6% loss
    ctrl.update_equity(-6.0)
    assert ctrl.in_safe_mode


def test_kill_switch_not_triggered_below_threshold():
    cfg = _cfg()
    ctrl = RiskController(cfg, initial_equity=100.0)
    ctrl.update_equity(-4.0)   # 4% loss < 5% threshold
    assert not ctrl.in_safe_mode


def test_stop_loss_triggers():
    cfg = _cfg()
    ctrl = RiskController(cfg, initial_equity=100.0)
    ctrl.record_open("EURUSD", entry_price=1.1000, direction="long", size=1.0)
    # Price drops 3% → exceeds 2% stop
    triggered = ctrl.check_stop_loss("EURUSD", current_price=1.1000 * 0.97)
    assert triggered


def test_stop_loss_not_triggered_within_limit():
    cfg = _cfg()
    ctrl = RiskController(cfg, initial_equity=100.0)
    ctrl.record_open("EURUSD", entry_price=1.1000, direction="long", size=1.0)
    # Price drops only 1%
    triggered = ctrl.check_stop_loss("EURUSD", current_price=1.1000 * 0.99)
    assert not triggered


def test_vol_target_scalar_normal():
    scalar = vol_target_scalar(realized_vol_annual=0.10, target_vol_annual=0.15, max_leverage=3.0)
    assert abs(scalar - 1.5) < 1e-6


def test_vol_target_scalar_capped():
    scalar = vol_target_scalar(realized_vol_annual=0.01, target_vol_annual=0.15, max_leverage=3.0)
    assert scalar == 3.0  # capped at max_leverage


def test_size_pairs_legs():
    size_a, size_b = size_pairs_legs(base_size=0.10, beta=0.8, max_position_pct=0.10)
    assert size_a == pytest.approx(0.10)
    assert size_b == pytest.approx(0.08)
