#!/usr/bin/env python3
"""
analyze_trades.py

Uses SHAP (github.com/shap/shap, 23k stars, MIT) to explain feature importance
for trade outcomes. Reads signals.csv + trades.csv from the latest walkforward
split and produces artifacts/latest_run/trade_analysis.json.

Output schema:
{
  "n_trades": int,
  "n_features": int,
  "feature_importance": [{"feature": str, "mean_abs_shap": float}],   # sorted desc
  "confidence_buckets": [{"bucket": str, "win_rate": float, "n": int}],
  "regime_accuracy": {"TREND": {"win_rate": float, "n": int}, ...},
  "model_score": {"accuracy": float, "auc": float},
  "top_features": [str]
}
"""

import json
import sys
from pathlib import Path


def find_latest_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    dirs = [d for d in base.iterdir() if d.is_dir()]
    return max(dirs, key=lambda d: d.stat().st_mtime) if dirs else None


def main() -> None:
    import csv
    repo_root = Path(__file__).parent.parent
    wf_root = repo_root / "artifacts" / "walkforward"
    out_dir = repo_root / "artifacts" / "latest_run"
    out_dir.mkdir(parents=True, exist_ok=True)

    wf_dir = find_latest_dir(wf_root)
    if not wf_dir:
        print("[analyze] No walkforward dir found — skipping", file=sys.stderr)
        return

    split_dir = wf_dir / "split_000"
    if not split_dir.exists():
        splits = sorted(wf_dir.glob("split_*"))
        split_dir = splits[0] if splits else None

    if not split_dir:
        print("[analyze] No split dir found — skipping", file=sys.stderr)
        return

    # Load signals and trades
    signals_path = split_dir / "hybrid" / "signals.csv"
    trades_path = split_dir / "hybrid" / "trades.csv"
    if not signals_path.exists():
        signals_path = split_dir / "trend_only" / "signals.csv"
    if not trades_path.exists():
        trades_path = split_dir / "trend_only" / "trades.csv"

    if not signals_path.exists() or not trades_path.exists():
        print("[analyze] signals.csv or trades.csv not found — skipping", file=sys.stderr)
        return

    try:
        import numpy as np
        import pandas as pd
    except ImportError:
        print("[analyze] pandas/numpy not available — skipping", file=sys.stderr)
        return

    try:
        import shap
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import accuracy_score, roc_auc_score
        from sklearn.model_selection import train_test_split
    except ImportError as e:
        print(f"[analyze] Missing dependency ({e}) — skipping", file=sys.stderr)
        return

    signals_df = pd.read_csv(signals_path)
    trades_df = pd.read_csv(trades_path)

    # Feature columns available in signals
    feature_cols = [c for c in [
        "confidence", "trend_p_up", "trend_p_down",
    ] if c in signals_df.columns]

    if not feature_cols or trades_df.empty:
        print("[analyze] Insufficient data for SHAP analysis", file=sys.stderr)
        return

    # Merge signals with trade outcomes on timestamp+symbol
    trades_df["entry_timestamp"] = pd.to_datetime(trades_df["entry_timestamp"], utc=True)
    signals_df["timestamp"] = pd.to_datetime(signals_df["timestamp"], utc=True)

    merged = pd.merge(
        signals_df[["timestamp", "symbol"] + feature_cols + ["regime_label"]],
        trades_df[["entry_timestamp", "symbol", "pnl"]],
        left_on=["timestamp", "symbol"],
        right_on=["entry_timestamp", "symbol"],
        how="inner",
    )

    if merged.empty or len(merged) < 5:
        print(f"[analyze] Only {len(merged)} matched rows — too few for SHAP", file=sys.stderr)
        return

    merged = merged.dropna(subset=feature_cols + ["pnl"])
    X = merged[feature_cols].astype(float)
    y = (merged["pnl"] > 0).astype(int)

    if y.nunique() < 2:
        print("[analyze] All trades same outcome — skipping", file=sys.stderr)
        return

    # Train RandomForest
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42
    )
    clf = RandomForestClassifier(n_estimators=50, random_state=42, max_depth=4)
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    accuracy = float(accuracy_score(y_test, y_pred))
    try:
        auc = float(roc_auc_score(y_test, clf.predict_proba(X_test)[:, 1]))
    except ValueError:
        auc = 0.0

    # SHAP values
    explainer = shap.TreeExplainer(clf)
    shap_values = explainer.shap_values(X)
    # For binary classification shap_values is [class0, class1]
    # For binary classification: sv shape is (n_samples, n_features, n_classes)
    sv_arr = np.array(shap_values)
    if sv_arr.ndim == 3:
        sv = np.abs(sv_arr[:, :, 1])
    elif isinstance(shap_values, list):
        sv = np.abs(np.array(shap_values[1]))
    else:
        sv = np.abs(sv_arr)

    mean_abs_shap = sv.mean(axis=0)
    feature_importance = sorted(
        [{"feature": f, "mean_abs_shap": float(v)} for f, v in zip(feature_cols, mean_abs_shap)],
        key=lambda x: x["mean_abs_shap"],
        reverse=True,
    )

    # Confidence buckets (win rate by confidence quintile)
    if "confidence" in merged.columns:
        merged["conf_bucket"] = pd.qcut(merged["confidence"], q=5, labels=False, duplicates="drop")
        conf_buckets = []
        for bucket, grp in merged.groupby("conf_bucket"):
            win_rate = float((grp["pnl"] > 0).mean())
            conf_buckets.append({
                "bucket": f"Q{int(bucket)+1}",
                "win_rate": round(win_rate, 4),
                "n": int(len(grp)),
                "avg_confidence": round(float(grp["confidence"].mean()), 4),
            })
    else:
        conf_buckets = []

    # Regime accuracy
    regime_accuracy: dict = {}
    if "regime_label" in merged.columns:
        for regime, grp in merged.groupby("regime_label"):
            regime_accuracy[str(regime)] = {
                "win_rate": round(float((grp["pnl"] > 0).mean()), 4),
                "n": int(len(grp)),
                "avg_pnl": round(float(grp["pnl"].mean()), 6),
            }

    result = {
        "n_trades": int(len(merged)),
        "n_features": len(feature_cols),
        "feature_importance": feature_importance,
        "confidence_buckets": conf_buckets,
        "regime_accuracy": regime_accuracy,
        "model_score": {"accuracy": round(accuracy, 4), "auc": round(auc, 4)},
        "top_features": [f["feature"] for f in feature_importance[:3]],
    }

    out_path = out_dir / "trade_analysis.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[analyze] Wrote trade_analysis.json ({len(merged)} trades, {len(feature_cols)} features, accuracy={accuracy:.3f})")


if __name__ == "__main__":
    main()
