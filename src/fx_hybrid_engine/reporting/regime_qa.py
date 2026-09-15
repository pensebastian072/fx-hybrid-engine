"""Regime QA helpers: churn, occupancy, posterior sanity and events."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from fx_hybrid_engine.utils.config import RegimeQAConfig


def regime_events(regime_df: pd.DataFrame) -> pd.DataFrame:
    """Emit transition events from ordered regime labels."""
    if regime_df.empty or "regime_label" not in regime_df.columns:
        return pd.DataFrame(columns=["timestamp", "from_regime", "to_regime"])
    frame = regime_df.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    prev = frame["regime_label"].shift(1)
    changed = frame.loc[prev.notna() & (frame["regime_label"] != prev)].copy()
    if changed.empty:
        return pd.DataFrame(columns=["timestamp", "from_regime", "to_regime"])
    changed["from_regime"] = prev.loc[changed.index].values
    changed["to_regime"] = changed["regime_label"].values
    return changed[["timestamp", "from_regime", "to_regime"]].reset_index(drop=True)


def summarize_regime_qa(
    regime_df: pd.DataFrame,
    *,
    cfg: RegimeQAConfig,
    hmm_state_map: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Build per-split regime QA summary and threshold checks."""
    if regime_df.empty:
        return {
            "enabled": cfg.enabled,
            "n_bars": 0,
            "n_transitions": 0,
            "transitions_per_1000_bars": 0.0,
            "occupancy": {"TREND": 0.0, "CHOP": 0.0, "RISK_OFF": 0.0},
            "max_posterior_sum_error": 1.0,
            "checks": {
                "posterior_sum_ok": False,
                "churn_ok": False,
                "occupancy_ok": False,
            },
            "pass": False,
            "hmm_state_map": hmm_state_map or {},
        }

    frame = regime_df.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")

    probs = frame[["TREND", "CHOP", "RISK_OFF"]].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    posterior_sum_error = (probs.sum(axis=1) - 1.0).abs()
    max_sum_err = float(posterior_sum_error.max()) if not posterior_sum_error.empty else 1.0

    events_df = regime_events(frame)
    n_bars = int(len(frame))
    n_trans = int(len(events_df))
    churn = float((n_trans / max(1, n_bars)) * 1000.0)

    occ = frame["regime_label"].value_counts(normalize=True).to_dict()
    occupancy = {
        "TREND": float(occ.get("TREND", 0.0)),
        "CHOP": float(occ.get("CHOP", 0.0)),
        "RISK_OFF": float(occ.get("RISK_OFF", 0.0)),
    }
    posterior_ok = max_sum_err <= float(cfg.max_posterior_sum_error)
    churn_ok = churn <= float(cfg.max_churn_per_1000_bars)
    occupancy_ok = all(v >= float(cfg.min_state_occupancy_share) or n_bars < 10 for v in occupancy.values())

    checks = {
        "posterior_sum_ok": posterior_ok,
        "churn_ok": churn_ok,
        "occupancy_ok": occupancy_ok,
    }
    return {
        "enabled": cfg.enabled,
        "n_bars": n_bars,
        "n_transitions": n_trans,
        "transitions_per_1000_bars": churn,
        "occupancy": occupancy,
        "max_posterior_sum_error": max_sum_err,
        "checks": checks,
        "pass": all(checks.values()),
        "thresholds": asdict(cfg),
        "hmm_state_map": hmm_state_map or {},
    }
