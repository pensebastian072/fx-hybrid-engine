from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from fx_hybrid_engine.ops.local_paper import run_local_paper_session
from fx_hybrid_engine.utils.config import load_config


def _cfg(tmp_path: Path):
    raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    raw["universe"]["pairs"] = [["EURUSD", "GBPUSD"]]
    raw["universe"]["pair_trade_universe"] = [["EURUSD", "GBPUSD"]]
    raw["universe"]["pair_observe_universe"] = ["EURUSD", "GBPUSD", "USDJPY"]
    raw["universe"]["trend_symbols"] = ["EURUSD", "GBPUSD"]
    raw["model_registry"]["root"] = str(tmp_path / "registry")
    raw["trend_engine"]["sma_fast"] = 10
    raw["trend_engine"]["sma_slow"] = 20
    raw["trend_engine"]["train_window_days"] = 5
    raw["trend_engine"]["test_window_days"] = 2
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config(cfg_path), cfg_path


def _synthetic_universe() -> dict[str, pd.DataFrame]:
    index = pd.date_range("2026-01-01", periods=40, freq="D", tz="UTC")
    symbols = {
        "EURUSD": 1.08,
        "GBPUSD": 1.27,
        "USDJPY": 148.0,
    }
    payload: dict[str, pd.DataFrame] = {}
    for offset, (symbol, base_price) in enumerate(symbols.items()):
        close = pd.Series(
            [base_price + 0.0015 * step + 0.0007 * offset for step in range(len(index))],
            index=index,
        )
        payload[symbol] = pd.DataFrame(
            {
                "open": close * 0.999,
                "high": close * 1.001,
                "low": close * 0.998,
                "close": close,
                "volume": 1000 + offset * 25,
            },
            index=index,
        )
    return payload


def test_run_local_paper_session_emits_strategy_and_helper_artifacts(tmp_path, monkeypatch):
    cfg, cfg_path = _cfg(tmp_path)
    monkeypatch.setattr(
        "fx_hybrid_engine.ops.local_paper.fetch_multi_symbol",
        lambda **_: _synthetic_universe(),
    )

    run_dir = run_local_paper_session(
        cfg=cfg,
        config_path=cfg_path,
        output_dir=tmp_path / "local_paper",
        run_id="local_paper_run",
    )

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["live_broker"] == "local"
    assert manifest["live_rail"] == "local_paper"

    state = json.loads((run_dir / "session_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "stopped"
    assert state["paper_strategy_status"] == "completed"

    for filename in [
        "paper_trades.json",
        "paper_position_plan.json",
        "paper_strategy_summary.json",
        "paper_safety_summary.json",
        "pairs_diagnostics.json",
        "pair_history.json",
        "signals_sample.json",
        "trend_model_meta.json",
        "paper_ops.json",
        "indicator_snapshots.json",
        "trend_decisions.json",
        "broker_context_latest.json",
    ]:
        assert (run_dir / filename).exists(), filename

    trend_model_meta = json.loads((run_dir / "trend_model_meta.json").read_text(encoding="utf-8"))
    assert trend_model_meta["model_version"]
    assert trend_model_meta["feature_columns"]

    pairs_diagnostics = json.loads((run_dir / "pairs_diagnostics.json").read_text(encoding="utf-8"))
    assert pairs_diagnostics
    assert any(row.get("in_trade_universe") for row in pairs_diagnostics)
    assert any(not row.get("in_trade_universe") for row in pairs_diagnostics)

    pair_history = json.loads((run_dir / "pair_history.json").read_text(encoding="utf-8"))
    assert "EURUSD-GBPUSD" in pair_history
    assert pair_history["EURUSD-GBPUSD"]["in_trade_universe"] is True

    paper_ops = json.loads((run_dir / "paper_ops.json").read_text(encoding="utf-8"))
    assert "broker_context" in paper_ops
    assert "no_trade_summary" in paper_ops

    paper_safety = json.loads((run_dir / "paper_safety_summary.json").read_text(encoding="utf-8"))
    assert paper_safety["reconciliation_mode"] == "skipped"
    assert paper_safety["reconciliation_status"] == "skipped"
    assert paper_safety["reconciliation_reason"] == "broker_state_unavailable_or_local_only"
