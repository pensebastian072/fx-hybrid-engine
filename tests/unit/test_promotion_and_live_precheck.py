from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from fx_hybrid_engine.brokers.base import BrokerAccount, BrokerBalance
from fx_hybrid_engine.ops.live_precheck import run_live_precheck
from fx_hybrid_engine.ops.model_registry import register_model_version
from fx_hybrid_engine.ops.promote_check import run_promotion_check
from fx_hybrid_engine.utils.config import load_config


def _cfg(tmp_path: Path):
    raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    raw["model_registry"]["root"] = str(tmp_path / "registry")
    raw["live_precheck"]["ladder_config_path"] = "config/ladder.yaml"
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config(cfg_path)


def _seed_registry(cfg, now: str) -> None:
    for model_type in ("trend", "hmm", "pairs"):
        register_model_version(
            cfg.model_registry,
            run_id=f"r_{model_type}",
            model_type=model_type,
            model_version="v1",
            training_window="2026-01-01..2026-01-31",
            feature_schema_version="f1",
            data_hash="h1",
            artifact_path="a",
            created_at_utc=now,
        )


def test_promote_check_outputs_deterministic_decision(tmp_path):
    cfg = _cfg(tmp_path)
    wf_dir = tmp_path / "wf"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "phase5_report_summary.json").write_text(
        json.dumps(
            {
                "final_go": True,
                "go_no_go": {
                    "costs_do_not_kill_edge": True,
                    "worst_split_drawdown_survivable": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (wf_dir / "proof_checks.json").write_text(json.dumps({"pass": True}), encoding="utf-8")
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"timestamp": "2026-01-01T00:00:00+00:00", "equity": 1.0, "run_id": "r1"}]).to_parquet(paper_dir / "equity_curve.parquet", index=False)
    pd.DataFrame([{"timestamp": "2026-01-01T00:00:00+00:00", "target_weight": 0.1, "run_id": "r1"}]).to_parquet(paper_dir / "targets.parquet", index=False)
    pd.DataFrame([{"timestamp": "2026-01-01T00:00:00+00:00", "reason": "ok", "run_id": "r1"}]).to_parquet(paper_dir / "risk_events.parquet", index=False)
    pd.DataFrame([{"timestamp": "2026-01-01T00:00:00+00:00", "regime_label": "TREND", "run_id": "r1"}]).to_parquet(paper_dir / "signals.parquet", index=False)
    (paper_dir / "broker_events.jsonl").write_text('{"timestamp":"2026-01-01T00:00:00+00:00","event":"ok","run_id":"r1"}\n', encoding="utf-8")
    (paper_dir / "reconciliation_events.jsonl").write_text('{"timestamp":"2026-01-01T00:00:00+00:00","reason":"ok","resolved":true,"run_id":"r1"}\n', encoding="utf-8")

    decision, out = run_promotion_check(cfg=cfg, wf_run_dir=wf_dir, paper_run_dir=paper_dir, window_days=14)
    assert out.exists()
    assert "ladder" in decision
    assert {"action", "current_stage", "next_stage"} <= set(decision["ladder"].keys())


def test_promote_check_does_not_count_skipped_reconciliation_as_failure(tmp_path):
    cfg = _cfg(tmp_path)
    wf_dir = tmp_path / "wf_skipped"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "phase5_report_summary.json").write_text(
        json.dumps(
            {
                "final_go": True,
                "go_no_go": {
                    "costs_do_not_kill_edge": True,
                    "worst_split_drawdown_survivable": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (wf_dir / "proof_checks.json").write_text(json.dumps({"pass": True}), encoding="utf-8")

    paper_dir = tmp_path / "paper_skipped"
    paper_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    pd.DataFrame([{"timestamp": now, "equity": 1.0, "run_id": "r1"}]).to_parquet(
        paper_dir / "equity_curve.parquet", index=False
    )
    pd.DataFrame([{"timestamp": now, "target_weight": 0.1, "run_id": "r1"}]).to_parquet(
        paper_dir / "targets.parquet", index=False
    )
    pd.DataFrame([{"timestamp": now, "reason": "ok", "run_id": "r1"}]).to_parquet(
        paper_dir / "risk_events.parquet", index=False
    )
    pd.DataFrame([{"timestamp": now, "regime_label": "TREND", "run_id": "r1"}]).to_parquet(
        paper_dir / "signals.parquet", index=False
    )
    (paper_dir / "broker_events.jsonl").write_text(
        json.dumps({"timestamp": now, "event": "ok", "run_id": "r1"}) + "\n",
        encoding="utf-8",
    )
    (paper_dir / "reconciliation_events.jsonl").write_text(
        json.dumps(
            {
                "timestamp": now,
                "event": "paper_reconciliation_skipped",
                "reconciliation_mode": "skipped",
                "reconciliation_status": "skipped",
                "reconciliation_reason": "broker_state_unavailable_or_local_only",
                "pause_entries": True,
                "resolved": False,
                "run_id": "r1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    decision, _ = run_promotion_check(cfg=cfg, wf_run_dir=wf_dir, paper_run_dir=paper_dir, window_days=14)
    assert decision["incident_counts"]["reconcile_failures"] == 0
    assert decision["incident_counts"]["reconcile_mode_counts"]["skipped"] == 1


def test_promote_check_infers_legacy_skipped_reconciliation_event(tmp_path):
    cfg = _cfg(tmp_path)
    wf_dir = tmp_path / "wf_legacy_skip"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "phase5_report_summary.json").write_text(
        json.dumps(
            {
                "final_go": True,
                "go_no_go": {
                    "costs_do_not_kill_edge": True,
                    "worst_split_drawdown_survivable": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (wf_dir / "proof_checks.json").write_text(json.dumps({"pass": True}), encoding="utf-8")

    paper_dir = tmp_path / "paper_legacy_skip"
    paper_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    pd.DataFrame([{"timestamp": now, "equity": 1.0, "run_id": "r1"}]).to_parquet(
        paper_dir / "equity_curve.parquet", index=False
    )
    pd.DataFrame([{"timestamp": now, "target_weight": 0.1, "run_id": "r1"}]).to_parquet(
        paper_dir / "targets.parquet", index=False
    )
    pd.DataFrame([{"timestamp": now, "reason": "ok", "run_id": "r1"}]).to_parquet(
        paper_dir / "risk_events.parquet", index=False
    )
    pd.DataFrame([{"timestamp": now, "regime_label": "TREND", "run_id": "r1"}]).to_parquet(
        paper_dir / "signals.parquet", index=False
    )
    (paper_dir / "broker_events.jsonl").write_text(
        json.dumps({"timestamp": now, "event": "ok", "run_id": "r1"}) + "\n",
        encoding="utf-8",
    )
    (paper_dir / "reconciliation_events.jsonl").write_text(
        json.dumps(
            {
                "timestamp": now,
                "event": "paper_reconciliation_skipped",
                "reason": "broker_state_unavailable_or_local_only",
                "pause_entries": True,
                "resolved": False,
                "run_id": "r1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    decision, _ = run_promotion_check(cfg=cfg, wf_run_dir=wf_dir, paper_run_dir=paper_dir, window_days=14)
    assert decision["incident_counts"]["reconcile_failures"] == 0
    assert decision["incident_counts"]["reconcile_mode_counts"]["skipped"] == 1


def test_live_precheck_passes_with_env_and_fresh_registry(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setenv("QC_USER_ID", "u")
    monkeypatch.setenv("QC_API_TOKEN", "t")
    now = datetime.now(UTC).isoformat()
    register_model_version(
        cfg.model_registry,
        run_id="r1",
        model_type="trend",
        model_version="v1",
        training_window="2026-01-01..2026-01-31",
        feature_schema_version="f1",
        data_hash="h1",
        artifact_path="a",
        created_at_utc=now,
    )
    register_model_version(
        cfg.model_registry,
        run_id="r2",
        model_type="hmm",
        model_version="v1",
        training_window="2026-01-01..2026-01-31",
        feature_schema_version="f2",
        data_hash="h2",
        artifact_path="b",
        created_at_utc=now,
    )
    register_model_version(
        cfg.model_registry,
        run_id="r3",
        model_type="pairs",
        model_version="v1",
        training_window="2026-01-01..2026-01-31",
        feature_schema_version="f3",
        data_hash="h3",
        artifact_path="c",
        created_at_utc=now,
    )
    report, out = run_live_precheck(cfg=cfg, output_path=tmp_path / "live_precheck.json")
    assert out.exists()
    assert report["pass"] is True
    assert report["checks"]["risk_caps_match_resolved_stage"] is True


def test_live_precheck_fails_when_stage_caps_exceed_risk_limit(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.risk.max_leverage = 0.01
    monkeypatch.setenv("QC_USER_ID", "u")
    monkeypatch.setenv("QC_API_TOKEN", "t")
    now = datetime.now(UTC).isoformat()
    _seed_registry(cfg, now)
    report, _ = run_live_precheck(cfg=cfg, output_path=tmp_path / "live_precheck_fail.json")
    assert report["pass"] is False
    assert report["checks"]["risk_caps_match_resolved_stage"] is False


def test_live_precheck_passes_for_tastytrade_with_mocked_api(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.live_execution.broker = "tastytrade"
    cfg.live_execution.rail = "tastytrade_paper"
    cfg.tastytrade.symbol_map = {
        symbol: f"TT_{symbol}"
        for symbol in sorted({s for pair in cfg.pair_list for s in pair} | set(cfg.trend_symbols))
    }
    monkeypatch.setenv("TASTYTRADE_CLIENT_ID", "cid")
    monkeypatch.setenv("TASTYTRADE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TASTYTRADE_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("TASTYTRADE_ACCOUNT_NUMBER", "5WT0001")

    now = datetime.now(UTC).isoformat()
    _seed_registry(cfg, now)

    class _FakeTastytradeClient:
        def list_accounts(self):
            return [BrokerAccount(account_number="5WT0001", authority_level="owner")]

        def get_balances(self, account_number: str):
            return BrokerBalance(account_number=account_number, raw={"cash-balance": "1000"})

    monkeypatch.setattr(
        "fx_hybrid_engine.ops.live_precheck._build_tastytrade_client",
        lambda _cfg: _FakeTastytradeClient(),
    )

    report, out = run_live_precheck(cfg=cfg, output_path=tmp_path / "live_precheck_tastytrade.json")
    assert out.exists()
    assert report["pass"] is True
    assert report["broker"] == "tastytrade"
    assert report["rail"] == "tastytrade_paper"
    assert report["checks"]["broker_api_reachable"] is True
    assert report["checks"]["broker_account_accessible"] is True
    assert report["checks"]["symbol_map_complete"] is True


def test_live_precheck_fails_for_tastytrade_when_symbol_map_missing(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.live_execution.broker = "tastytrade"
    cfg.live_execution.rail = "tastytrade_paper"
    cfg.tastytrade.validate_api_on_precheck = False
    cfg.tastytrade.symbol_map = {}
    monkeypatch.setenv("TASTYTRADE_CLIENT_ID", "cid")
    monkeypatch.setenv("TASTYTRADE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TASTYTRADE_REFRESH_TOKEN", "refresh")

    now = datetime.now(UTC).isoformat()
    _seed_registry(cfg, now)

    report, _ = run_live_precheck(cfg=cfg, output_path=tmp_path / "live_precheck_tastytrade_fail.json")
    assert report["pass"] is False
    assert report["checks"]["symbol_map_complete"] is False
    assert report["broker"] == "tastytrade"


def test_live_precheck_blocks_tastytrade_live_when_phase3_flags_disabled(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.live_execution.broker = "tastytrade"
    cfg.live_execution.rail = "tastytrade_live"
    cfg.live_execution.enable_broker_native_orders = False
    cfg.live_execution.enable_broker_market_data = False
    cfg.tastytrade.validate_api_on_precheck = False
    cfg.tastytrade.symbol_map = {
        symbol: f"TT_{symbol}"
        for symbol in sorted({s for pair in cfg.pair_list for s in pair} | set(cfg.trend_symbols))
    }
    monkeypatch.setenv("TASTYTRADE_CLIENT_ID", "cid")
    monkeypatch.setenv("TASTYTRADE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TASTYTRADE_REFRESH_TOKEN", "refresh")

    now = datetime.now(UTC).isoformat()
    _seed_registry(cfg, now)

    report, _ = run_live_precheck(cfg=cfg, output_path=tmp_path / "live_precheck_tastytrade_gated.json")
    assert report["pass"] is False
    assert report["broker_native_requested"] is True
    assert report["broker_native_blockers"] == [
        "enable_broker_native_orders_disabled",
        "enable_broker_market_data_disabled",
    ]
    assert report["checks"]["broker_native_orders_enabled_for_requested_rail"] is False
    assert report["checks"]["broker_market_data_enabled_for_requested_rail"] is False
