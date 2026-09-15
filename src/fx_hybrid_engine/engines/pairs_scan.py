"""Rolling pair scan and diagnostics for explainable Phase 2 behavior."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fx_hybrid_engine.features.spread import compute_spread, hedge_ratio, is_cointegrated, zscore


@dataclass(slots=True)
class PairScanResult:
    candidates: pd.DataFrame
    scans: pd.DataFrame
    diagnostics: pd.DataFrame


def _scan_points(index: pd.DatetimeIndex, min_train_bars: int, scan_frequency_bars: int) -> list[int]:
    if len(index) == 0:
        return []
    if len(index) < min_train_bars:
        return [len(index) - 1]
    points = list(range(min_train_bars - 1, len(index), max(1, scan_frequency_bars)))
    if points[-1] != len(index) - 1:
        points.append(len(index) - 1)
    return points


def scan_candidate_pairs(
    data: dict[str, pd.DataFrame],
    pair_list: list[list[str]],
    *,
    cointegration_threshold: float,
    spread_window: int,
    entry_zscore: float,
    min_train_bars: int,
    scan_frequency_bars: int,
) -> PairScanResult:
    """Run rolling scans and return candidate + scan + diagnostic tables."""
    candidate_rows: list[dict[str, object]] = []
    scan_rows: list[dict[str, object]] = []
    pair_ids: list[str] = []

    for pair in pair_list:
        if len(pair) < 2:
            continue
        sym_a, sym_b = str(pair[0]), str(pair[1])
        pair_id = f"{sym_a}-{sym_b}"
        pair_ids.append(pair_id)
        candidate_rows.append({"pair_id": pair_id, "sym_a": sym_a, "sym_b": sym_b})
        if sym_a not in data or sym_b not in data:
            scan_rows.append(
                {
                    "timestamp": pd.NaT,
                    "scan_idx": 0,
                    "pair_id": pair_id,
                    "sym_a": sym_a,
                    "sym_b": sym_b,
                    "n_bars": 0,
                    "pvalue": np.nan,
                    "beta": np.nan,
                    "spread_std": np.nan,
                    "z_abs_p95": np.nan,
                    "is_cointegrated": False,
                    "reason": "missing_symbol_data",
                }
            )
            continue

        close_a = data[sym_a]["close"]
        close_b = data[sym_b]["close"]
        common = close_a.index.intersection(close_b.index)
        close_a = close_a.reindex(common).dropna()
        close_b = close_b.reindex(common).dropna()
        common = close_a.index.intersection(close_b.index)
        close_a = close_a.reindex(common)
        close_b = close_b.reindex(common)
        if len(common) == 0:
            scan_rows.append(
                {
                    "timestamp": pd.NaT,
                    "scan_idx": 0,
                    "pair_id": pair_id,
                    "sym_a": sym_a,
                    "sym_b": sym_b,
                    "n_bars": 0,
                    "pvalue": np.nan,
                    "beta": np.nan,
                    "spread_std": np.nan,
                    "z_abs_p95": np.nan,
                    "is_cointegrated": False,
                    "reason": "missing_symbol_data",
                }
            )
            continue

        points = _scan_points(pd.DatetimeIndex(common), min_train_bars=min_train_bars, scan_frequency_bars=scan_frequency_bars)
        for scan_idx, end_pos in enumerate(points):
            ts = pd.Timestamp(common[end_pos]).isoformat()
            hist_a = close_a.iloc[: end_pos + 1]
            hist_b = close_b.iloc[: end_pos + 1]
            n_bars = len(hist_a)
            if n_bars < min_train_bars:
                scan_rows.append(
                    {
                        "timestamp": ts,
                        "scan_idx": scan_idx,
                        "pair_id": pair_id,
                        "sym_a": sym_a,
                        "sym_b": sym_b,
                        "n_bars": n_bars,
                        "pvalue": np.nan,
                        "beta": np.nan,
                        "spread_std": np.nan,
                        "z_abs_p95": np.nan,
                        "is_cointegrated": False,
                        "reason": "insufficient_bars",
                    }
                )
                continue

            cointegrated, pvalue = is_cointegrated(hist_a, hist_b, cointegration_threshold)
            beta = hedge_ratio(hist_a, hist_b)
            spread = compute_spread(hist_a, hist_b, beta)
            zs = zscore(spread, spread_window)
            spread_std = float(spread.std()) if len(spread) > 1 else 0.0
            z_abs_p95 = float(zs.abs().quantile(0.95)) if len(zs.dropna()) > 0 else 0.0
            scan_rows.append(
                {
                    "timestamp": ts,
                    "scan_idx": scan_idx,
                    "pair_id": pair_id,
                    "sym_a": sym_a,
                    "sym_b": sym_b,
                    "n_bars": n_bars,
                    "pvalue": float(pvalue),
                    "beta": float(beta),
                    "spread_std": spread_std,
                    "z_abs_p95": z_abs_p95,
                    "is_cointegrated": bool(cointegrated),
                    "reason": "ok",
                }
            )

    candidates_df = pd.DataFrame(candidate_rows, columns=["pair_id", "sym_a", "sym_b"])
    scans_df = pd.DataFrame(
        scan_rows,
        columns=[
            "timestamp",
            "scan_idx",
            "pair_id",
            "sym_a",
            "sym_b",
            "n_bars",
            "pvalue",
            "beta",
            "spread_std",
            "z_abs_p95",
            "is_cointegrated",
            "reason",
        ],
    )
    diagnostics_df = build_pairs_diagnostics(
        scans_df,
        pair_ids=pair_ids,
        cointegration_threshold=cointegration_threshold,
        entry_zscore=entry_zscore,
    )
    return PairScanResult(candidates=candidates_df, scans=scans_df, diagnostics=diagnostics_df)


def build_pairs_diagnostics(
    scans_df: pd.DataFrame,
    *,
    pair_ids: list[str],
    cointegration_threshold: float,
    entry_zscore: float,
    state_map: dict[str, str] | None = None,
    trade_counts: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Build one-row-per-pair diagnostics with primary no-trade reason taxonomy."""
    state_map = state_map or {}
    trade_counts = trade_counts or {}
    rows: list[dict[str, object]] = []
    for pair_id in pair_ids:
        sub = scans_df.loc[scans_df["pair_id"] == pair_id].copy() if not scans_df.empty else pd.DataFrame()
        if sub.empty:
            rows.append(
                {
                    "pair_id": pair_id,
                    "scan_rows": 0,
                    "latest_pvalue": np.nan,
                    "latest_beta": np.nan,
                    "latest_spread_std": np.nan,
                    "latest_z_abs_p95": np.nan,
                    "state": state_map.get(pair_id, "WATCH"),
                    "trade_count": int(trade_counts.get(pair_id, 0)),
                    "primary_reason": "missing_symbol_data",
                }
            )
            continue

        valid = sub.loc[sub["reason"] == "ok"].copy()
        latest = sub.iloc[-1]
        latest_p = latest.get("pvalue", np.nan)
        latest_beta = latest.get("beta", np.nan)
        latest_std = latest.get("spread_std", np.nan)
        latest_z95 = latest.get("z_abs_p95", np.nan)
        state = str(state_map.get(pair_id, "WATCH"))
        trades = int(trade_counts.get(pair_id, 0))

        if (sub["reason"] == "insufficient_bars").all():
            reason = "insufficient_bars"
        elif (sub["reason"] == "missing_symbol_data").all():
            reason = "missing_symbol_data"
        elif valid.empty or not bool((valid["pvalue"] <= cointegration_threshold).any()):
            reason = "pvalue_fail"
        elif not bool((valid["z_abs_p95"] >= entry_zscore).any()):
            reason = "z_never_hit_entry"
        elif state == "DISABLED":
            reason = "breakdown_disabled"
        elif state != "TRADABLE":
            reason = "state_not_tradable"
        else:
            reason = "tradable"

        rows.append(
            {
                "pair_id": pair_id,
                "scan_rows": int(len(sub)),
                "latest_pvalue": latest_p,
                "latest_beta": latest_beta,
                "latest_spread_std": latest_std,
                "latest_z_abs_p95": latest_z95,
                "state": state,
                "trade_count": trades,
                "primary_reason": reason,
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "pair_id",
            "scan_rows",
            "latest_pvalue",
            "latest_beta",
            "latest_spread_std",
            "latest_z_abs_p95",
            "state",
            "trade_count",
            "primary_reason",
        ],
    )
