"""Phase 5 proof report generator."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from fx_hybrid_engine.utils.config import ProofGatesConfig


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _fmt(x: float) -> str:
    return f"{x:.4f}"


def _df_to_md(df: pd.DataFrame, index: bool = False) -> str:
    """Render DataFrame as markdown without optional tabulate dependency."""
    if df.empty:
        return "No data."
    frame = df.copy()
    if index:
        frame = frame.reset_index()
    cols = [str(c) for c in frame.columns]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = []
    for _, row in frame.iterrows():
        vals = [str(row[c]) for c in frame.columns]
        rows.append("| " + " | ".join(vals) + " |")
    return "\n".join([header, sep, *rows])


def _load_proof_gates(root: Path) -> ProofGatesConfig:
    snapshot = root / "split_000" / "hybrid" / "config_snapshot.yaml"
    if not snapshot.exists():
        return ProofGatesConfig()
    try:
        raw = yaml.safe_load(snapshot.read_text(encoding="utf-8")) or {}
        gates_raw = (raw.get("config") or {}).get("proof_gates") or {}
        return ProofGatesConfig(**gates_raw)
    except Exception:
        return ProofGatesConfig()


def generate_phase5_report(run_dir: str | Path) -> tuple[Path, Path]:
    root = Path(run_dir)
    metrics = _read_csv(root / "metrics_by_split.csv")
    by_engine = _read_csv(root / "pnl_attribution_engine.csv")
    by_regime = _read_csv(root / "pnl_attribution_regime.csv")
    by_engine_regime = _read_csv(root / "pnl_attribution_engine_x_regime.csv")
    pairs_diag = _read_csv(root / "pairs_diagnostics_by_split.csv")
    regime_qa = _read_csv(root / "regime_qa_by_split.csv")
    regime_compare = _read_csv(root / "regime_comparison_metrics.csv")
    cost_sweep = _read_csv(root / "robustness_cost_sweep.csv")
    param_sweep = _read_csv(root / "robustness_param_sweep.csv")
    proof = json.loads((root / "proof_checks.json").read_text(encoding="utf-8")) if (root / "proof_checks.json").exists() else {"pass": False, "checks": {}}
    robust_diag = json.loads((root / "robustness_diagnostics.json").read_text(encoding="utf-8")) if (root / "robustness_diagnostics.json").exists() else {}
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8")) if (root / "run_manifest.json").exists() else {}

    hybrid = metrics.loc[metrics["mode"] == "hybrid"].copy() if not metrics.empty else pd.DataFrame()
    pairs_only = metrics.loc[metrics["mode"] == "pairs_only"].copy() if not metrics.empty else pd.DataFrame()
    trend_only = metrics.loc[metrics["mode"] == "trend_only"].copy() if not metrics.empty else pd.DataFrame()

    summary_by_mode = (
        metrics.groupby("mode")[["total_return", "sharpe", "max_drawdown", "trades"]]
        .agg(["mean", "median", "std"])
        .round(6)
        if not metrics.empty
        else pd.DataFrame()
    )

    worst_split = None
    worst_reason = "No hybrid split data"
    if not hybrid.empty:
        worst_row = hybrid.sort_values("total_return").iloc[0]
        worst_split = int(worst_row["split_idx"])
        eq_path = root / f"split_{worst_split:03d}" / "hybrid" / "equity_curve.csv"
        reg_path = root / f"split_{worst_split:03d}" / "hybrid" / "regime_posteriors.csv"
        eq = _read_csv(eq_path)
        reg = _read_csv(reg_path)
        churn = float(eq["turnover"].mean()) if "turnover" in eq.columns and not eq.empty else 0.0
        costs = float(eq["costs"].sum()) if "costs" in eq.columns and not eq.empty else 0.0
        regime_mix = reg["regime_label"].value_counts(normalize=True).to_dict() if "regime_label" in reg.columns and not reg.empty else {}
        worst_reason = (
            f"Regime mix={regime_mix}, mean turnover={churn:.4f}, cumulative costs={costs:.4f}, "
            f"max_dd={float(worst_row['max_drawdown']):.4f}"
        )

    def _median(df: pd.DataFrame, col: str) -> float:
        return float(df[col].median()) if (not df.empty and col in df.columns) else 0.0

    hybrid_beats_pairs = (_median(hybrid, "sharpe") > _median(pairs_only, "sharpe")) and (_median(hybrid, "total_return") > _median(pairs_only, "total_return"))
    hybrid_beats_trend = (_median(hybrid, "sharpe") > _median(trend_only, "sharpe")) and (_median(hybrid, "total_return") > _median(trend_only, "total_return"))
    worst_dd = float(hybrid["max_drawdown"].max()) if not hybrid.empty else 1.0

    worst_cost_row = cost_sweep.loc[cost_sweep["scenario"] == "worst_case"] if not cost_sweep.empty else pd.DataFrame()
    costs_survivable = (float(worst_cost_row["total_return"].median()) > 0.0) if not worst_cost_row.empty else False

    pos_share = float(robust_diag.get("positive_return_share", 0.0))
    sharpe_share = float(robust_diag.get("non_negative_sharpe_share", 0.0))

    proof_checks = proof.get("checks", {})
    pair_concentration_check = proof_checks.get("pair_profit_concentration", {"pass": False, "value": 1.0})
    if not metrics.empty and "trend_model_version" in metrics.columns:
        unique_model_versions = sorted(metrics["trend_model_version"].dropna().astype(str).unique().tolist())
        trend_model_consistency_ok = len(unique_model_versions) <= 1
    else:
        unique_model_versions = []
        trend_model_consistency_ok = True

    unique_schema_hashes: list[str] = []
    if not metrics.empty and "trend_feature_schema_hash" in metrics.columns:
        unique_schema_hashes = sorted(metrics["trend_feature_schema_hash"].dropna().astype(str).unique().tolist())

    gates = _load_proof_gates(root)
    go_no_go = {
        "hybrid_beats_pairs_only": hybrid_beats_pairs,
        "hybrid_beats_trend_only": hybrid_beats_trend,
        "worst_split_drawdown_survivable": worst_dd <= gates.max_worst_split_drawdown,
        "costs_do_not_kill_edge": costs_survivable,
        "attribution_matches_theory": bool(proof.get("pass", False)),
        "pair_profit_concentration_ok": bool(pair_concentration_check.get("pass", False)),
        "trend_model_version_consistent": trend_model_consistency_ok,
        "param_sweep_positive_return_share_ok": pos_share >= gates.min_positive_param_sweep_share,
        "param_sweep_sharpe_share_ok": sharpe_share >= gates.min_non_negative_sharpe_param_sweep_share,
    }
    final_go = all(go_no_go.values())

    report_lines = []
    report_lines.append("# Phase 5 Proof Report")
    report_lines.append("")
    report_lines.append(f"Run Directory: `{root}`")
    report_lines.append(f"Overall Go/No-Go: **{'GO' if final_go else 'NO-GO'}**")
    report_lines.append("")

    report_lines.append("## Cross-Split Summary")
    if summary_by_mode.empty:
        report_lines.append("No metrics available.")
    else:
        report_lines.append(_df_to_md(summary_by_mode, index=True))
    report_lines.append("")

    report_lines.append("## Hybrid vs Baselines (Median)")
    compare = pd.DataFrame(
        [
            {"mode": "hybrid", "median_total_return": _median(hybrid, "total_return"), "median_sharpe": _median(hybrid, "sharpe"), "median_max_drawdown": _median(hybrid, "max_drawdown")},
            {"mode": "pairs_only", "median_total_return": _median(pairs_only, "total_return"), "median_sharpe": _median(pairs_only, "sharpe"), "median_max_drawdown": _median(pairs_only, "max_drawdown")},
            {"mode": "trend_only", "median_total_return": _median(trend_only, "total_return"), "median_sharpe": _median(trend_only, "sharpe"), "median_max_drawdown": _median(trend_only, "max_drawdown")},
        ]
    )
    report_lines.append(_df_to_md(compare, index=False))
    report_lines.append("")

    report_lines.append("## Worst Split")
    report_lines.append(f"Worst split index: `{worst_split}`")
    report_lines.append(worst_reason)
    report_lines.append("")

    report_lines.append("## Attribution")
    report_lines.append("### PnL by Engine")
    report_lines.append(_df_to_md(by_engine, index=False))
    report_lines.append("")
    report_lines.append("### PnL by Regime")
    report_lines.append(_df_to_md(by_regime, index=False))
    report_lines.append("")
    report_lines.append("### PnL by Engine x Regime")
    report_lines.append(_df_to_md(by_engine_regime, index=False))
    report_lines.append("")
    if not pairs_diag.empty:
        report_lines.append("### Pairs Diagnostics")
        report_lines.append(_df_to_md(pairs_diag, index=False))
        report_lines.append("")

    if not regime_qa.empty:
        report_lines.append("## Regime QA")
        report_lines.append(_df_to_md(regime_qa, index=False))
        report_lines.append("")

    if not regime_compare.empty:
        report_lines.append("## Regime Comparison")
        report_lines.append(_df_to_md(regime_compare, index=False))
        report_lines.append("")

    report_lines.append("## Trend Model Traceability")
    report_lines.append(f"Requested model version: `{manifest.get('trend_model_requested', 'n/a')}`")
    report_lines.append(f"Manifest feature schema hash: `{manifest.get('trend_feature_schema_hash', 'n/a')}`")
    report_lines.append(f"Observed model versions in metrics: `{unique_model_versions}`")
    report_lines.append(f"Observed feature schema hashes in metrics: `{unique_schema_hashes}`")
    report_lines.append(f"Model version consistency check: **{'PASS' if trend_model_consistency_ok else 'FAIL'}**")
    report_lines.append("")

    report_lines.append("## Robustness")
    report_lines.append("### Cost Sweep")
    report_lines.append(_df_to_md(cost_sweep, index=False))
    report_lines.append("")
    report_lines.append("### Parameter Sweep")
    report_lines.append(_df_to_md(param_sweep, index=False))
    report_lines.append("")
    report_lines.append(f"Positive-return share: {_fmt_pct(pos_share)}")
    report_lines.append(f"Non-negative-Sharpe share: {_fmt_pct(sharpe_share)}")
    report_lines.append(f"Relative return degradation: {_fmt(float(robust_diag.get('relative_return_degradation', 0.0)))}")
    report_lines.append("")

    report_lines.append("## Go/No-Go Checklist")
    for key, val in go_no_go.items():
        report_lines.append(f"- {'PASS' if val else 'FAIL'}: {key}")
    report_lines.append("")

    summary = {
        "run_dir": str(root),
        "final_go": final_go,
        "go_no_go": go_no_go,
        "median_hybrid_total_return": _median(hybrid, "total_return"),
        "median_hybrid_sharpe": _median(hybrid, "sharpe"),
        "worst_split_max_drawdown": worst_dd,
        "trend_model_versions": unique_model_versions,
        "trend_feature_schema_hashes": unique_schema_hashes,
    }

    md_path = root / "phase5_proof_report.md"
    json_path = root / "phase5_report_summary.json"
    md_path.write_text("\n".join(report_lines), encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return md_path, json_path
