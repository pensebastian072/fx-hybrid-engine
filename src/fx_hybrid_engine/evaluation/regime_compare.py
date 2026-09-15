"""Regime policy comparison: hmm vs heuristic vs none."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fx_hybrid_engine.engines.pairs import PairsEngine
from fx_hybrid_engine.engines.trend import TrendEngine
from fx_hybrid_engine.engines.types import Direction, EngineOutput, Signal
from fx_hybrid_engine.evaluation.local_backtester import run_local_backtest
from fx_hybrid_engine.features.indicators import momentum_slope, rolling_vol
from fx_hybrid_engine.regime.hmm import CHOP, RISK_OFF, TREND, RegimeHMM
from fx_hybrid_engine.regime.orchestrator import RegimeOrchestrator
from fx_hybrid_engine.utils.config import EngineConfig


class _HeuristicOrchestrator:
    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        self._current_state = CHOP
        self._state_probabilities = {TREND: 0.0, CHOP: 1.0, RISK_OFF: 0.0}
        self._vol_hist: list[float] = []
        self._mom_hist: list[float] = []

    def _z(self, values: list[float], x: float) -> float:
        if len(values) < 10:
            return 0.0
        arr = np.asarray(values[-200:], dtype=float)
        std = float(arr.std())
        if std <= 1e-12:
            return 0.0
        return float((x - float(arr.mean())) / std)

    def update_regime(self, data: dict[str, pd.DataFrame]) -> str:
        obs: list[tuple[float, float]] = []
        for df in data.values():
            if "close" not in df.columns or len(df) < self.cfg.regime.vol_window + 2:
                continue
            vol = rolling_vol(df["close"], window=self.cfg.regime.vol_window, annualize=True).iloc[-1]
            mom = momentum_slope(df["close"], window=self.cfg.regime.vol_window).iloc[-1]
            if pd.isna(vol) or pd.isna(mom):
                continue
            obs.append((float(vol), float(mom)))
        if not obs:
            return self._current_state
        vol_now = float(np.mean([v for v, _ in obs]))
        mom_now = float(np.mean([m for _, m in obs]))
        self._vol_hist.append(vol_now)
        self._mom_hist.append(mom_now)
        vol_z = self._z(self._vol_hist, vol_now)
        mom_z = self._z(self._mom_hist, mom_now)
        rc = self.cfg.regime_compare
        if vol_z >= rc.heuristic_vol_z_risk_off:
            self._current_state = RISK_OFF
            self._state_probabilities = {TREND: 0.0, CHOP: 0.0, RISK_OFF: 1.0}
        elif abs(mom_z) >= rc.heuristic_mom_z_trend and vol_z <= rc.heuristic_vol_z_trend_max:
            self._current_state = TREND
            self._state_probabilities = {TREND: 1.0, CHOP: 0.0, RISK_OFF: 0.0}
        else:
            self._current_state = CHOP
            self._state_probabilities = {TREND: 0.0, CHOP: 1.0, RISK_OFF: 0.0}
        return self._current_state

    def gate(
        self,
        pairs_output: EngineOutput,
        trend_output: EngineOutput,
        timestamp: pd.Timestamp,
        mode: str = "hybrid",
    ) -> list[Signal]:
        if self._current_state == RISK_OFF:
            # Mirror orchestrator behavior: no new entries in risk-off.
            return [
                sig for sig in (list(pairs_output.signals) + list(trend_output.signals))
                if sig.direction == Direction.FLAT or sig.size == 0
            ]
        if self._current_state == TREND:
            return list(trend_output.signals)
        return list(pairs_output.signals)

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def state_probabilities(self) -> dict[str, float]:
        return dict(self._state_probabilities)


class _NoGateOrchestrator(_HeuristicOrchestrator):
    def gate(
        self,
        pairs_output: EngineOutput,
        trend_output: EngineOutput,
        timestamp: pd.Timestamp,
        mode: str = "hybrid",
    ) -> list[Signal]:
        # No gating baseline: pass both engines through.
        return list(pairs_output.signals) + list(trend_output.signals)


def run_regime_comparison_for_split(
    *,
    cfg: EngineConfig,
    eval_data: dict[str, pd.DataFrame],
    test_index: pd.DatetimeIndex,
    pairs_engine: PairsEngine,
    trend_engine: TrendEngine,
    hmm_model: RegimeHMM | None,
    split_idx: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for policy in cfg.regime_compare.policies:
        if policy == "hmm":
            orch = RegimeOrchestrator(cfg.regime, cfg.risk)
            if hmm_model is not None:
                orch._hmm = hmm_model  # noqa: SLF001
        elif policy == "heuristic":
            orch = _HeuristicOrchestrator(cfg)
        elif policy == "none":
            orch = _NoGateOrchestrator(cfg)
        else:
            continue

        result = run_local_backtest(
            cfg=cfg,
            aligned_data=eval_data,
            test_index=test_index,
            pairs_engine=pairs_engine,
            trend_engine=trend_engine,
            orchestrator=orch,  # type: ignore[arg-type]
            costs=cfg.execution_costs,
            mode="hybrid",
            precomputed_steps=None,
        )
        rows.append(
            {
                "split_idx": split_idx,
                "policy": policy,
                "total_return": float(result.metrics.get("total_return", 0.0)),
                "sharpe": float(result.metrics.get("sharpe", 0.0)),
                "max_drawdown": float(result.metrics.get("max_drawdown", 0.0)),
                "trades": int(result.metrics.get("trades", 0)),
            }
        )
    return pd.DataFrame(rows, columns=["split_idx", "policy", "total_return", "sharpe", "max_drawdown", "trades"])


def write_regime_comparison_report(df: pd.DataFrame, out_dir: str | Path) -> Path:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    md = root / "regime_comparison_report.md"
    if df.empty:
        md.write_text("# Regime Comparison Report\n\nNo data.\n", encoding="utf-8")
        return md
    pivot = (
        df.groupby("policy")[["total_return", "sharpe", "max_drawdown", "trades"]]
        .median()
        .reset_index()
        .sort_values("policy")
    )
    baseline = pivot.loc[pivot["policy"] == "hmm"].copy()
    lines = ["# Regime Comparison Report", ""]
    header = "| policy | total_return | sharpe | max_drawdown | trades |"
    sep = "| --- | --- | --- | --- | --- |"
    lines.extend([header, sep])
    for row in pivot.itertuples(index=False):
        lines.append(
            f"| {row.policy} | {row.total_return:.6f} | {row.sharpe:.6f} | {row.max_drawdown:.6f} | {int(row.trades)} |"
        )
    lines.append("")
    if not baseline.empty:
        b = baseline.iloc[0]
        lines.append("## Deltas vs HMM")
        for row in pivot.itertuples(index=False):
            if row.policy == "hmm":
                continue
            lines.append(
                f"- {row.policy}: "
                f"delta_return={row.total_return - b.total_return:.6f}, "
                f"delta_sharpe={row.sharpe - b.sharpe:.6f}, "
                f"delta_max_drawdown={row.max_drawdown - b.max_drawdown:.6f}, "
                f"delta_trades={int(row.trades - b.trades)}"
            )
    md.write_text("\n".join(lines), encoding="utf-8")
    (root / "regime_comparison_report.json").write_text(
        json.dumps(df.to_dict(orient="records"), indent=2, default=float),
        encoding="utf-8",
    )
    return md
