"""PnL attribution and proof-gate checks for Phase 5."""
from __future__ import annotations

import math

import pandas as pd

from fx_hybrid_engine.utils.config import ProofGatesConfig


def _empty_with_columns(cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=cols)


def pnl_attribution_engine(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return _empty_with_columns(["engine_source", "n_trades", "total_pnl", "win_rate", "pnl_share"])
    grouped = trades.groupby("engine_source", dropna=False)
    out = grouped.agg(
        n_trades=("pnl", "size"),
        total_pnl=("pnl", "sum"),
        win_rate=("pnl", lambda s: float((s > 0).mean()) if len(s) else 0.0),
    ).reset_index()
    denom = float(out["total_pnl"].abs().sum())
    out["pnl_share"] = out["total_pnl"].abs() / denom if denom > 0 else 0.0
    return out.sort_values("total_pnl", ascending=False)


def pnl_attribution_regime(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return _empty_with_columns(["entry_regime", "n_trades", "total_pnl", "win_rate", "pnl_share"])
    grouped = trades.groupby("entry_regime", dropna=False)
    out = grouped.agg(
        n_trades=("pnl", "size"),
        total_pnl=("pnl", "sum"),
        win_rate=("pnl", lambda s: float((s > 0).mean()) if len(s) else 0.0),
    ).reset_index()
    denom = float(out["total_pnl"].abs().sum())
    out["pnl_share"] = out["total_pnl"].abs() / denom if denom > 0 else 0.0
    return out.sort_values("total_pnl", ascending=False)


def pnl_attribution_engine_x_regime(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return _empty_with_columns(["engine_source", "entry_regime", "n_trades", "total_pnl", "win_rate", "pnl_share_within_engine"])
    grouped = trades.groupby(["engine_source", "entry_regime"], dropna=False)
    out = grouped.agg(
        n_trades=("pnl", "size"),
        total_pnl=("pnl", "sum"),
        win_rate=("pnl", lambda s: float((s > 0).mean()) if len(s) else 0.0),
    ).reset_index()
    out["abs_pnl"] = out["total_pnl"].abs()
    denom = out.groupby("engine_source")["abs_pnl"].transform("sum")
    out["pnl_share_within_engine"] = out["abs_pnl"] / denom.replace(0.0, math.nan)
    out["pnl_share_within_engine"] = out["pnl_share_within_engine"].fillna(0.0)
    return out.drop(columns=["abs_pnl"]).sort_values(["engine_source", "total_pnl"], ascending=[True, False])


def pair_profit_concentration(trades: pd.DataFrame) -> float:
    """Return max share of absolute pair pnl accounted by one pair_id."""
    pairs = trades.loc[trades["pair_id"].notna()].copy()
    if pairs.empty:
        return 0.0
    by_pair = pairs.groupby("pair_id")["pnl"].sum().abs()
    denom = float(by_pair.sum())
    if denom == 0:
        return 0.0
    return float(by_pair.max() / denom)


def evaluate_proof_checks(
    trades: pd.DataFrame,
    gates: ProofGatesConfig,
) -> dict[str, object]:
    """Compute pass/fail checks backing the Phase 5 report go/no-go section."""
    hybrid = trades.loc[trades["mode"] == "hybrid"].copy() if "mode" in trades.columns else trades.copy()
    if hybrid.empty:
        return {
            "pass": False,
            "reason": "No hybrid trades available for proof checks",
            "checks": {},
        }

    exr = pnl_attribution_engine_x_regime(hybrid)
    engine_totals = hybrid.groupby("engine_source")["pnl"].apply(lambda s: float(s.abs().sum())).to_dict()

    def _share(engine: str, regime: str) -> float:
        sub = exr[(exr["engine_source"] == engine) & (exr["entry_regime"] == regime)]
        if sub.empty:
            return 0.0
        return float(sub["pnl_share_within_engine"].iloc[0])

    trend_share = _share("trend", "TREND")
    pairs_share = _share("pairs", "CHOP")

    total_abs = float(hybrid["pnl"].abs().sum())
    risk_off_abs = float(hybrid.loc[hybrid["entry_regime"] == "RISK_OFF", "pnl"].abs().sum())
    risk_off_abs_share = (risk_off_abs / total_abs) if total_abs > 0 else 0.0
    risk_off_entry_count = int((hybrid["entry_regime"] == "RISK_OFF").sum())

    pair_concentration = pair_profit_concentration(hybrid)

    checks = {
        "trend_pnl_in_trend": {
            "value": trend_share,
            "threshold": gates.min_trend_pnl_in_trend_share,
            "pass": trend_share >= gates.min_trend_pnl_in_trend_share,
        },
        "pairs_pnl_in_chop": {
            "value": pairs_share,
            "threshold": gates.min_pairs_pnl_in_chop_share,
            "pass": pairs_share >= gates.min_pairs_pnl_in_chop_share,
        },
        "risk_off_abs_pnl_share": {
            "value": risk_off_abs_share,
            "threshold": gates.max_risk_off_pnl_share_abs,
            "pass": risk_off_abs_share <= gates.max_risk_off_pnl_share_abs,
        },
        "risk_off_entry_count": {
            "value": risk_off_entry_count,
            "threshold": 0,
            "pass": risk_off_entry_count == 0,
        },
        "pair_profit_concentration": {
            "value": pair_concentration,
            "threshold": gates.max_pair_profit_concentration,
            "pass": pair_concentration <= gates.max_pair_profit_concentration,
        },
    }

    return {
        "pass": all(v["pass"] for v in checks.values()),
        "checks": checks,
        "engine_abs_pnl": engine_totals,
    }

