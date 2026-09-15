"""Weekly Phase 7 evaluation orchestration and promotion decisioning."""
from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path

from fx_hybrid_engine.evaluation.walkforward import run_walkforward
from fx_hybrid_engine.ops.alerts import append_alert
from fx_hybrid_engine.ops.ladder import decide_ladder_action
from fx_hybrid_engine.ops.promote_check import run_promotion_check
from fx_hybrid_engine.utils.config import load_config


def run_weekly_evaluation(
    *,
    config_path: str | Path = "config/default.yaml",
    run_id: str | None = None,
) -> tuple[Path, Path]:
    cfg = load_config(config_path)
    wf_run = run_walkforward(
        config_path=config_path,
        wf_run_id=run_id,
        max_splits=cfg.weekly_evaluation.max_splits,
        run_report=True,
        skip_robustness=not cfg.weekly_evaluation.run_robustness,
        precompute=True,
        mode_reuse=True,
    )
    summary_path = wf_run / "phase5_report_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing phase5 report summary: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    final_go = bool(summary.get("final_go", False))
    go_no_go = summary.get("go_no_go", {})
    severe_fail = (
        (not final_go)
        and (
            not bool(go_no_go.get("costs_do_not_kill_edge", True))
            or not bool(go_no_go.get("attribution_matches_theory", True))
            or not bool(go_no_go.get("worst_split_drawdown_survivable", True))
        )
    )
    ladder = decide_ladder_action(
        cfg.micro_live_ladder.active_stage,
        final_go=final_go,
        severe_fail=severe_fail,
    )
    decision = {
        "run_dir": str(wf_run),
        "final_go": final_go,
        "go_no_go": go_no_go,
        "ladder": ladder,
    }
    decision_path = wf_run / "decision.json"
    decision_path.write_text(json.dumps(decision, indent=2), encoding="utf-8")

    if not final_go:
        manifest_path = wf_run / "run_manifest.json"
        run_identity = wf_run.name
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                run_identity = str(manifest.get("wf_run_id", run_identity))
            except Exception:  # noqa: BLE001
                pass
        append_alert(
            wf_run,
            run_id=run_identity,
            severity="warning",
            alert_type="weekly_go_no_go_failure",
            message="Weekly evaluation failed go/no-go gates",
            details={"go_no_go": go_no_go, "ladder": ladder},
            cfg=cfg.alerts,
        )

    # Optional promotion decision when paper artifacts are available.
    paper_candidates = sorted(Path(cfg.ops.output_root).glob("paper/*/*"))
    if paper_candidates:
        latest_paper = paper_candidates[-1]
        with suppress(Exception):
            _decision, _promotion_path = run_promotion_check(
                cfg=cfg,
                wf_run_dir=wf_run,
                paper_run_dir=latest_paper,
                window_days=cfg.promotion.paper_window_days,
            )
    return wf_run, decision_path
