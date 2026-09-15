"""Local deterministic backtester used by Phase 5 walk-forward evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from fx_hybrid_engine.engines.pairs import PairsEngine
from fx_hybrid_engine.engines.trend import TrendEngine
from fx_hybrid_engine.engines.types import EngineOutput, EngineType, Signal
from fx_hybrid_engine.portfolio.builder import PortfolioBuilder
from fx_hybrid_engine.regime.orchestrator import RegimeOrchestrator
from fx_hybrid_engine.reporting.metrics import max_drawdown, sharpe_ratio, win_rate
from fx_hybrid_engine.risk.controls import RiskController
from fx_hybrid_engine.utils.config import EngineConfig, ExecutionCostsConfig

Mode = Literal["hybrid", "pairs_only", "trend_only"]


@dataclass(slots=True)
class LocalBacktestResult:
    signals: pd.DataFrame
    fills: pd.DataFrame
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    regime_posteriors: pd.DataFrame
    engine_allocations: pd.DataFrame
    metrics: dict[str, float]


@dataclass(slots=True)
class PrecomputedStep:
    """Precomputed per-timestamp market state + engine outputs."""

    timestamp: pd.Timestamp
    prices: dict[str, float]
    regime_label: str
    probabilities: dict[str, float]
    pairs_signals: list[Signal]
    trend_signals: list[Signal]


def _periods_per_year(bar_frequency: str) -> int:
    freq = bar_frequency.lower()
    if freq == "1d":
        return 252
    if freq == "1h":
        return 252 * 24
    if freq in ("15m", "30m"):
        mins = 15 if freq == "15m" else 30
        return int((252 * 24 * 60) / mins)
    return 252


def _sign(x: float, eps: float = 1e-10) -> int:
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


def _as_utc(ts: object) -> pd.Timestamp:
    out = pd.Timestamp(ts)
    if out.tzinfo is None:
        return out.tz_localize("UTC")
    return out.tz_convert("UTC")


def _dominant_engine(signals: list[Signal], symbol: str, fallback: str = "unknown") -> tuple[str, str | None]:
    agg: dict[str, float] = {}
    pair_id: str | None = None
    for sig in signals:
        if sig.symbol != symbol or not sig.is_active():
            continue
        key = str(sig.engine.value)
        agg[key] = agg.get(key, 0.0) + abs(sig.size)
        if pair_id is None:
            pair_id = sig.metadata.get("pair_id") if sig.metadata else None
    if not agg:
        return fallback, pair_id
    engine = max(agg.items(), key=lambda kv: kv[1])[0]
    return engine, pair_id


def run_local_backtest(
    cfg: EngineConfig,
    aligned_data: dict[str, pd.DataFrame],
    test_index: pd.DatetimeIndex,
    pairs_engine: PairsEngine,
    trend_engine: TrendEngine,
    orchestrator: RegimeOrchestrator,
    costs: ExecutionCostsConfig,
    mode: Mode = "hybrid",
    precomputed_steps: list[PrecomputedStep] | None = None,
) -> LocalBacktestResult:
    """Backtest one split in local deterministic mode and emit full artifacts."""
    portfolio = PortfolioBuilder(cfg.risk)
    risk = RiskController(cfg.risk, initial_equity=1.0)
    test_index = pd.DatetimeIndex(sorted(pd.to_datetime(test_index, utc=True).unique()))

    signals_rows: list[dict[str, object]] = []
    fill_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []
    regime_rows: list[dict[str, object]] = []
    alloc_rows: list[dict[str, object]] = []

    equity = 1.0
    prev_prices: dict[str, float] | None = None
    prev_weights: dict[str, float] = {}
    open_positions: dict[str, dict[str, object]] = {}

    def close_trade(
        symbol: str,
        exit_ts: pd.Timestamp,
        exit_price: float,
        exit_regime: str,
        reason: str = "signal_flip_or_flat",
    ) -> None:
        if symbol not in open_positions:
            return
        pos = open_positions.pop(symbol)
        entry_price = float(pos["entry_price"])
        entry_equity = float(pos["entry_equity"])
        entry_weight = float(pos["entry_weight"])
        direction = int(pos["direction"])
        raw_ret = (exit_price / entry_price) - 1.0 if entry_price != 0 else 0.0
        signed_ret = raw_ret * direction
        pnl = signed_ret * abs(entry_weight) * entry_equity
        trade_rows.append(
            {
                "entry_timestamp": _as_utc(pos["entry_timestamp"]).isoformat(),
                "exit_timestamp": exit_ts.isoformat(),
                "symbol": symbol,
                "engine_source": pos["engine_source"],
                "entry_regime": pos["entry_regime"],
                "exit_regime": exit_regime,
                "pair_id": pos.get("pair_id"),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "entry_weight": entry_weight,
                "entry_regime_prob_trend": float(pos.get("entry_regime_prob_trend", 0.0)),
                "entry_regime_prob_chop": float(pos.get("entry_regime_prob_chop", 0.0)),
                "entry_regime_prob_risk_off": float(pos.get("entry_regime_prob_risk_off", 0.0)),
                "close_reason": reason,
                "pnl": float(pnl),
                "mode": mode,
            }
        )

    all_symbols = list(aligned_data.keys())
    trend_symbols = [s for s in cfg.trend_symbols if s in aligned_data]

    if precomputed_steps is not None:
        iter_steps = sorted(precomputed_steps, key=lambda s: s.timestamp)
    else:
        iter_steps = []

    if precomputed_steps is None:
        for bar_idx, ts in enumerate(test_index):
            bar_data = {sym: df.loc[:ts] for sym, df in aligned_data.items() if ts in df.index}
            if not bar_data:
                continue
            current_prices = {sym: float(df["close"].iloc[-1]) for sym, df in bar_data.items()}

            prev_equity = equity
            if prev_prices is not None:
                gross_ret = 0.0
                for sym, w in prev_weights.items():
                    prev_px = prev_prices.get(sym)
                    curr_px = current_prices.get(sym)
                    if prev_px is None or curr_px is None or prev_px == 0:
                        continue
                    gross_ret += w * ((curr_px / prev_px) - 1.0)
                equity *= 1.0 + gross_ret
            else:
                gross_ret = 0.0

            if risk.in_safe_mode:
                regime = "RISK_OFF"
                gated: list[Signal] = []
                target: dict[str, float] = {}
                probabilities = {"TREND": 0.0, "CHOP": 0.0, "RISK_OFF": 1.0}
            else:
                regime = orchestrator.update_regime(bar_data)
                pairs_out = pairs_engine.generate(bar_data, ts)
                trend_data = {s: bar_data[s] for s in trend_symbols if s in bar_data}
                trend_out = trend_engine.generate(trend_data, ts)
                gated = orchestrator.gate(pairs_out, trend_out, ts, mode=mode)
                target = portfolio.build(gated)
                probabilities = {
                    "TREND": float(orchestrator.state_probabilities.get("TREND", 0.0)),
                    "CHOP": float(orchestrator.state_probabilities.get("CHOP", 0.0)),
                    "RISK_OFF": float(orchestrator.state_probabilities.get("RISK_OFF", 0.0)),
                }

            forced_flat_symbols: set[str] = set()
            max_hold = int(getattr(getattr(cfg, "pairs_policy", object()), "max_holding_bars", 0) or 0)
            if max_hold > 0:
                for sym, pos in list(open_positions.items()):
                    entry_bar_idx = int(pos.get("entry_bar_idx", bar_idx))
                    if (bar_idx - entry_bar_idx) >= max_hold and sym in current_prices:
                        close_trade(sym, ts, current_prices[sym], regime, reason="time_stop")
                        forced_flat_symbols.add(sym)
            for sym in forced_flat_symbols:
                target[sym] = 0.0

            engine_abs = {"pairs": 0.0, "trend": 0.0}
            for sig in gated:
                meta = sig.metadata or {}
                signals_rows.append(
                    {
                        "timestamp": ts.isoformat(),
                        "symbol": sig.symbol,
                        "direction": sig.direction.value,
                        "size": float(sig.size),
                        "engine_source": str(sig.engine.value),
                        "confidence": float(sig.confidence),
                        "regime_label": regime,
                        "pair_id": meta.get("pair_id"),
                        "trend_p_up": meta.get("p_up"),
                        "trend_p_down": meta.get("p_down"),
                        "decision_threshold": meta.get("decision_threshold"),
                        "trend_model_version": meta.get("model_version"),
                        "mode": mode,
                    }
                )
                if sig.is_active():
                    engine_abs[str(sig.engine.value)] += abs(sig.size)

            alloc_rows.append(
                {
                    "timestamp": ts.isoformat(),
                    "pairs_alloc": float(engine_abs["pairs"]),
                    "trend_alloc": float(engine_abs["trend"]),
                    "total_alloc": float(engine_abs["pairs"] + engine_abs["trend"]),
                    "regime_label": regime,
                    "mode": mode,
                }
            )
            regime_rows.append(
                {
                    "timestamp": ts.isoformat(),
                    "regime_label": regime,
                    "TREND": probabilities["TREND"],
                    "CHOP": probabilities["CHOP"],
                    "RISK_OFF": probabilities["RISK_OFF"],
                    "mode": mode,
                }
            )

            symbols_union = sorted(set(all_symbols) | set(prev_weights.keys()) | set(target.keys()))
            turnover = 0.0
            for sym in symbols_union:
                prev_w = float(prev_weights.get(sym, 0.0))
                new_w = float(target.get(sym, 0.0))
                delta = new_w - prev_w
                turnover += abs(delta)
                if abs(delta) <= 1e-12:
                    continue
                price = current_prices.get(sym)
                if price is None:
                    continue
                fallback_engine = str(open_positions.get(sym, {}).get("engine_source", "unknown"))
                engine_source, pair_id = _dominant_engine(gated, sym, fallback=fallback_engine)
                fill_rows.append(
                    {
                        "timestamp": ts.isoformat(),
                        "symbol": sym,
                        "prev_weight": prev_w,
                        "target_weight": new_w,
                        "delta_weight": delta,
                        "price": price,
                        "engine_source": engine_source,
                        "regime_label": regime,
                        "pair_id": pair_id or open_positions.get(sym, {}).get("pair_id"),
                        "commission_bps": float(costs.commission_bps),
                        "slippage_bps": float(costs.slippage_bps),
                        "mode": mode,
                    }
                )

                prev_sign = _sign(prev_w)
                new_sign = _sign(new_w)
                if sym in open_positions and (new_sign == 0 or new_sign != prev_sign):
                    close_trade(sym, ts, price, regime, reason="signal_flip_or_flat")
                if new_sign != 0 and (sym not in open_positions):
                    open_positions[sym] = {
                        "entry_timestamp": ts,
                        "entry_price": price,
                        "entry_weight": new_w,
                        "entry_equity": equity,
                        "direction": new_sign,
                        "engine_source": engine_source,
                        "entry_regime": regime,
                        "pair_id": pair_id,
                        "entry_bar_idx": bar_idx,
                        "entry_regime_prob_trend": float(probabilities.get("TREND", 0.0)),
                        "entry_regime_prob_chop": float(probabilities.get("CHOP", 0.0)),
                        "entry_regime_prob_risk_off": float(probabilities.get("RISK_OFF", 0.0)),
                    }

            total_bps = float(costs.commission_bps + costs.slippage_bps)
            costs_value = equity * turnover * (total_bps / 10_000.0)
            equity -= costs_value
            pnl_delta = equity - prev_equity
            risk.update_equity(pnl_delta)
            net_ret = (equity / prev_equity) - 1.0 if prev_equity != 0 else 0.0

            equity_rows.append(
                {
                    "timestamp": ts.isoformat(),
                    "equity": float(equity),
                    "gross_return": float(gross_ret),
                    "net_return": float(net_ret),
                    "turnover": float(turnover),
                    "costs": float(costs_value),
                    "regime_label": regime,
                    "mode": mode,
                }
            )

            prev_weights = target
            prev_prices = current_prices
    else:
        for bar_idx, step in enumerate(iter_steps):
            ts = _as_utc(step.timestamp)
            current_prices = {k: float(v) for k, v in step.prices.items()}

            prev_equity = equity
            if prev_prices is not None:
                gross_ret = 0.0
                for sym, w in prev_weights.items():
                    prev_px = prev_prices.get(sym)
                    curr_px = current_prices.get(sym)
                    if prev_px is None or curr_px is None or prev_px == 0:
                        continue
                    gross_ret += w * ((curr_px / prev_px) - 1.0)
                equity *= 1.0 + gross_ret
            else:
                gross_ret = 0.0

            if risk.in_safe_mode:
                regime = "RISK_OFF"
                probabilities = {"TREND": 0.0, "CHOP": 0.0, "RISK_OFF": 1.0}
                gated = []
                target = {}
            else:
                regime = str(step.regime_label)
                probabilities = {
                    "TREND": float(step.probabilities.get("TREND", 0.0)),
                    "CHOP": float(step.probabilities.get("CHOP", 0.0)),
                    "RISK_OFF": float(step.probabilities.get("RISK_OFF", 0.0)),
                }
                orchestrator._current_state = regime  # noqa: SLF001
                orchestrator._state_probabilities = probabilities.copy()  # noqa: SLF001
                pairs_out = EngineOutput(engine=EngineType.PAIRS, timestamp=ts, signals=list(step.pairs_signals))
                trend_out = EngineOutput(engine=EngineType.TREND, timestamp=ts, signals=list(step.trend_signals))
                gated = orchestrator.gate(pairs_out, trend_out, ts, mode=mode)
                target = portfolio.build(gated)

            forced_flat_symbols: set[str] = set()
            max_hold = int(getattr(getattr(cfg, "pairs_policy", object()), "max_holding_bars", 0) or 0)
            if max_hold > 0:
                for sym, pos in list(open_positions.items()):
                    entry_bar_idx = int(pos.get("entry_bar_idx", bar_idx))
                    if (bar_idx - entry_bar_idx) >= max_hold and sym in current_prices:
                        close_trade(sym, ts, current_prices[sym], regime, reason="time_stop")
                        forced_flat_symbols.add(sym)
            for sym in forced_flat_symbols:
                target[sym] = 0.0

            engine_abs = {"pairs": 0.0, "trend": 0.0}
            for sig in gated:
                meta = sig.metadata or {}
                signals_rows.append(
                    {
                        "timestamp": ts.isoformat(),
                        "symbol": sig.symbol,
                        "direction": sig.direction.value,
                        "size": float(sig.size),
                        "engine_source": str(sig.engine.value),
                        "confidence": float(sig.confidence),
                        "regime_label": regime,
                        "pair_id": meta.get("pair_id"),
                        "trend_p_up": meta.get("p_up"),
                        "trend_p_down": meta.get("p_down"),
                        "decision_threshold": meta.get("decision_threshold"),
                        "trend_model_version": meta.get("model_version"),
                        "mode": mode,
                    }
                )
                if sig.is_active():
                    engine_abs[str(sig.engine.value)] += abs(sig.size)

            alloc_rows.append(
                {
                    "timestamp": ts.isoformat(),
                    "pairs_alloc": float(engine_abs["pairs"]),
                    "trend_alloc": float(engine_abs["trend"]),
                    "total_alloc": float(engine_abs["pairs"] + engine_abs["trend"]),
                    "regime_label": regime,
                    "mode": mode,
                }
            )
            regime_rows.append(
                {
                    "timestamp": ts.isoformat(),
                    "regime_label": regime,
                    "TREND": probabilities["TREND"],
                    "CHOP": probabilities["CHOP"],
                    "RISK_OFF": probabilities["RISK_OFF"],
                    "mode": mode,
                }
            )

            symbols_union = sorted(set(all_symbols) | set(prev_weights.keys()) | set(target.keys()))
            turnover = 0.0
            for sym in symbols_union:
                prev_w = float(prev_weights.get(sym, 0.0))
                new_w = float(target.get(sym, 0.0))
                delta = new_w - prev_w
                turnover += abs(delta)
                if abs(delta) <= 1e-12:
                    continue
                price = current_prices.get(sym)
                if price is None:
                    continue
                fallback_engine = str(open_positions.get(sym, {}).get("engine_source", "unknown"))
                engine_source, pair_id = _dominant_engine(gated, sym, fallback=fallback_engine)
                fill_rows.append(
                    {
                        "timestamp": ts.isoformat(),
                        "symbol": sym,
                        "prev_weight": prev_w,
                        "target_weight": new_w,
                        "delta_weight": delta,
                        "price": price,
                        "engine_source": engine_source,
                        "regime_label": regime,
                        "pair_id": pair_id or open_positions.get(sym, {}).get("pair_id"),
                        "commission_bps": float(costs.commission_bps),
                        "slippage_bps": float(costs.slippage_bps),
                        "mode": mode,
                    }
                )

                prev_sign = _sign(prev_w)
                new_sign = _sign(new_w)
                if sym in open_positions and (new_sign == 0 or new_sign != prev_sign):
                    close_trade(sym, ts, price, regime, reason="signal_flip_or_flat")
                if new_sign != 0 and (sym not in open_positions):
                    open_positions[sym] = {
                        "entry_timestamp": ts,
                        "entry_price": price,
                        "entry_weight": new_w,
                        "entry_equity": equity,
                        "direction": new_sign,
                        "engine_source": engine_source,
                        "entry_regime": regime,
                        "pair_id": pair_id,
                        "entry_bar_idx": bar_idx,
                        "entry_regime_prob_trend": float(probabilities.get("TREND", 0.0)),
                        "entry_regime_prob_chop": float(probabilities.get("CHOP", 0.0)),
                        "entry_regime_prob_risk_off": float(probabilities.get("RISK_OFF", 0.0)),
                    }

            total_bps = float(costs.commission_bps + costs.slippage_bps)
            costs_value = equity * turnover * (total_bps / 10_000.0)
            equity -= costs_value
            pnl_delta = equity - prev_equity
            risk.update_equity(pnl_delta)
            net_ret = (equity / prev_equity) - 1.0 if prev_equity != 0 else 0.0

            equity_rows.append(
                {
                    "timestamp": ts.isoformat(),
                    "equity": float(equity),
                    "gross_return": float(gross_ret),
                    "net_return": float(net_ret),
                    "turnover": float(turnover),
                    "costs": float(costs_value),
                    "regime_label": regime,
                    "mode": mode,
                }
            )

            prev_weights = target
            prev_prices = current_prices

    if len(test_index) > 0:
        last_ts = test_index[-1]
        for sym, pos in list(open_positions.items()):
            price = aligned_data[sym].loc[:last_ts]["close"].iloc[-1] if sym in aligned_data else pos["entry_price"]
            close_trade(sym, _as_utc(last_ts), float(price), "END", reason="end_of_test")

    signals_df = pd.DataFrame(
        signals_rows,
        columns=[
            "timestamp",
            "symbol",
            "direction",
            "size",
            "engine_source",
            "confidence",
            "regime_label",
            "pair_id",
            "trend_p_up",
            "trend_p_down",
            "decision_threshold",
            "trend_model_version",
            "mode",
        ],
    )
    fills_df = pd.DataFrame(
        fill_rows,
        columns=[
            "timestamp",
            "symbol",
            "prev_weight",
            "target_weight",
            "delta_weight",
            "price",
            "engine_source",
            "regime_label",
            "pair_id",
            "commission_bps",
            "slippage_bps",
            "mode",
        ],
    )
    trades_df = pd.DataFrame(
        trade_rows,
        columns=[
            "entry_timestamp",
            "exit_timestamp",
            "symbol",
            "engine_source",
            "entry_regime",
            "exit_regime",
            "pair_id",
            "entry_price",
            "exit_price",
            "entry_weight",
            "entry_regime_prob_trend",
            "entry_regime_prob_chop",
            "entry_regime_prob_risk_off",
            "close_reason",
            "pnl",
            "mode",
        ],
    )
    equity_df = pd.DataFrame(
        equity_rows,
        columns=["timestamp", "equity", "gross_return", "net_return", "turnover", "costs", "regime_label", "mode"],
    )
    regime_df = pd.DataFrame(
        regime_rows,
        columns=["timestamp", "regime_label", "TREND", "CHOP", "RISK_OFF", "mode"],
    )
    alloc_df = pd.DataFrame(
        alloc_rows,
        columns=["timestamp", "pairs_alloc", "trend_alloc", "total_alloc", "regime_label", "mode"],
    )

    net_returns = equity_df["net_return"] if not equity_df.empty else pd.Series(dtype=float)
    equity_series = equity_df["equity"] if not equity_df.empty else pd.Series(dtype=float)
    periods = _periods_per_year(cfg.data.bar_frequency)
    metrics = {
        "total_return": float(equity_series.iloc[-1] - 1.0) if not equity_df.empty else 0.0,
        "sharpe": sharpe_ratio(net_returns, periods_per_year=periods) if not equity_df.empty else 0.0,
        "max_drawdown": max_drawdown(equity_series) if not equity_df.empty else 0.0,
        "win_rate": win_rate(net_returns) if not equity_df.empty else 0.0,
        "trades": int(len(trades_df)),
    }

    return LocalBacktestResult(
        signals=signals_df,
        fills=fills_df,
        trades=trades_df,
        equity_curve=equity_df,
        regime_posteriors=regime_df,
        engine_allocations=alloc_df,
        metrics=metrics,
    )
