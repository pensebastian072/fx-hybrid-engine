"""Risk controls: stop-loss enforcement and drawdown kill-switch."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fx_hybrid_engine.utils.config import RiskConfig

logger = logging.getLogger("fxhe.risk.controls")


@dataclass
class PositionRecord:
    symbol: str
    entry_price: float
    direction: str           # "long" or "short"
    size: float


@dataclass
class RiskController:
    """Tracks portfolio equity and enforces stop-loss and drawdown limits."""

    config: RiskConfig
    initial_equity: float = 1.0
    _peak_equity: float = field(init=False, default=1.0)
    _current_equity: float = field(init=False, default=1.0)
    _safe_mode: bool = field(init=False, default=False)
    _open_positions: dict[str, PositionRecord] = field(init=False, default_factory=dict)
    _event_log: list[dict[str, object]] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._peak_equity = self.initial_equity
        self._current_equity = self.initial_equity

    def update_equity(self, pnl: float) -> None:
        """Update equity with a PnL delta and check kill-switch."""
        self._current_equity += pnl
        if self._current_equity > self._peak_equity:
            self._peak_equity = self._current_equity
        drawdown = (self._peak_equity - self._current_equity) / self._peak_equity
        if drawdown >= self.config.drawdown_kill_pct and not self._safe_mode:
            logger.warning(
                "Drawdown %.2f%% exceeded kill threshold %.2f%% — entering SAFE MODE",
                drawdown * 100,
                self.config.drawdown_kill_pct * 100,
            )
            self._safe_mode = True
            self._event_log.append(
                {
                    "reason": "drawdown_kill_switch",
                    "drawdown": drawdown,
                    "threshold": self.config.drawdown_kill_pct,
                    "safe_mode": True,
                }
            )

    def reset_safe_mode(self) -> None:
        """Manually reset safe mode (requires operator approval)."""
        self._safe_mode = False
        logger.info("Safe mode reset")

    @property
    def in_safe_mode(self) -> bool:
        return self._safe_mode

    @property
    def current_drawdown(self) -> float:
        if self._peak_equity == 0:
            return 0.0
        return (self._peak_equity - self._current_equity) / self._peak_equity

    def check_stop_loss(self, symbol: str, current_price: float) -> bool:
        """Return True if the position has hit its stop-loss level."""
        rec = self._open_positions.get(symbol)
        if rec is None:
            return False
        move = (current_price - rec.entry_price) / rec.entry_price
        if rec.direction == "short":
            move = -move
        if move <= -self.config.stop_loss_pct:
            logger.info("Stop-loss triggered for %s: move=%.2f%%", symbol, move * 100)
            self._event_log.append(
                {
                    "reason": "stop_loss_triggered",
                    "symbol": symbol,
                    "move": move,
                    "threshold": self.config.stop_loss_pct,
                }
            )
            return True
        return False

    def record_open(self, symbol: str, entry_price: float, direction: str, size: float) -> None:
        self._open_positions[symbol] = PositionRecord(symbol, entry_price, direction, size)

    def record_close(self, symbol: str) -> None:
        self._open_positions.pop(symbol, None)

    @property
    def event_log(self) -> list[dict[str, object]]:
        return list(self._event_log)
