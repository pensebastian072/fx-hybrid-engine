from __future__ import annotations

import json
from pathlib import Path

import yaml

from fx_hybrid_engine.brokers.base import BrokerAccount, BrokerBalance
from fx_hybrid_engine.brokers.tastytrade_live import run_tastytrade_live_session
from fx_hybrid_engine.utils.config import load_config


def _cfg(tmp_path: Path):
    raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    raw["universe"]["pairs"] = [["EURUSD", "GBPUSD"]]
    raw["universe"]["trend_symbols"] = ["EURUSD", "GBPUSD"]
    raw["model_registry"]["root"] = str(tmp_path / "registry")
    raw["live_execution"]["broker"] = "tastytrade"
    raw["live_execution"]["rail"] = "tastytrade_paper"
    raw["trend_engine"]["sma_fast"] = 10
    raw["trend_engine"]["sma_slow"] = 20
    raw["trend_engine"]["train_window_days"] = 5
    raw["trend_engine"]["test_window_days"] = 2
    raw["tastytrade"]["symbol_map"] = {
        "AUDUSD": "6A",
        "EURUSD": "6E",
        "GBPUSD": "6B",
        "USDJPY": "6J",
        "USDCHF": "6S",
        "NZDUSD": "6N",
        "USDCAD": "6C",
    }
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config(cfg_path), cfg_path


def _cfg_live_native(tmp_path: Path):
    cfg, cfg_path = _cfg(tmp_path)
    cfg.live_execution.rail = "tastytrade_live"
    cfg.live_execution.enable_broker_native_orders = True
    cfg.live_execution.enable_broker_market_data = True
    return cfg, cfg_path


def test_run_tastytrade_live_session_bootstraps_ops_run(tmp_path):
    cfg, cfg_path = _cfg(tmp_path)

    class _FakeClient:
        def list_accounts(self):
            return [BrokerAccount(account_number="5WT0001", authority_level="owner")]

        def get_balances(self, account_number: str):
            return BrokerBalance(account_number=account_number, raw={"cash-balance": "1000.00"})

    def _fake_strategy_runner(**_kwargs):
        return {"status": "completed", "last_regime": "TREND"}

    run_dir = run_tastytrade_live_session(
        cfg=cfg,
        config_path=cfg_path,
        output_dir=tmp_path / "paper",
        run_id="taste_run",
        client_builder=lambda _cfg: _FakeClient(),
        strategy_runner=_fake_strategy_runner,
    )

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["live_broker"] == "tastytrade"
    assert manifest["live_rail"] == "tastytrade_paper"
    assert manifest["tastytrade"]["account_number"] == "5WT0001"
    assert manifest["tastytrade"]["symbol_map"]["EURUSD"] == "6E"

    state = json.loads((run_dir / "session_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "stopped"
    assert state["broker"] == "tastytrade"

    events = [
        json.loads(line)
        for line in (run_dir / "broker_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event"] for event in events] == [
        "session_start",
        "account_resolved",
        "balance_snapshot",
        "session_stop",
    ]
    assert events[0]["rail"] == "tastytrade_paper"
    assert events[0]["broker"] == "tastytrade"


def test_run_tastytrade_live_session_emits_strategy_cycle_outputs(tmp_path):
    cfg, cfg_path = _cfg(tmp_path)

    class _FakeClient:
        def list_accounts(self):
            return [BrokerAccount(account_number="5WT0001", authority_level="owner")]

        def get_balances(self, account_number: str):
            return BrokerBalance(account_number=account_number, raw={"cash-balance": "1000.00"})

    run_dir = run_tastytrade_live_session(
        cfg=cfg,
        config_path=cfg_path,
        output_dir=tmp_path / "paper_cycle",
        run_id="taste_cycle",
        client_builder=lambda _cfg: _FakeClient(),
    )

    strategy_summary = json.loads(
        (run_dir / "paper_strategy_summary.json").read_text(encoding="utf-8")
    )
    assert strategy_summary["status"] == "completed"
    assert strategy_summary["broker_order_routing"] == "local_paper_only"
    assert strategy_summary["paper_rollout_profile"]["active_strategy_stack"] == [
        "pairs",
        "trend",
        "regime_hmm",
    ]
    assert "safety_summary" in strategy_summary
    assert (run_dir / "ops_summary.json").exists()
    assert (run_dir / "paper_trades.json").exists()
    assert (run_dir / "paper_position_plan.json").exists()
    assert (run_dir / "paper_safety_summary.json").exists()
    assert (run_dir / "pairs_diagnostics.json").exists()
    assert (run_dir / "pair_history.json").exists()
    assert (run_dir / "signals_sample.json").exists()
    assert (run_dir / "trend_model_meta.json").exists()

    bars = json.loads((run_dir / "bar_health.json").read_text(encoding="utf-8"))
    assert isinstance(bars, list)
    position_plan = json.loads((run_dir / "paper_position_plan.json").read_text(encoding="utf-8"))
    assert isinstance(position_plan, list)
    assert all("orderable_contract_ready" in row for row in position_plan)
    pair_history = json.loads((run_dir / "pair_history.json").read_text(encoding="utf-8"))
    trend_model_meta = json.loads((run_dir / "trend_model_meta.json").read_text(encoding="utf-8"))
    assert isinstance(pair_history, dict)
    assert trend_model_meta["model_version"]

    state = json.loads((run_dir / "session_state.json").read_text(encoding="utf-8"))
    assert state["paper_strategy_status"] == "completed"
    assert "close_only" in state
    assert "health_state" in state

    events = [
        json.loads(line)
        for line in (run_dir / "broker_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(event["event"] == "strategy_cycle_complete" for event in events)


def test_run_tastytrade_live_session_requires_explicit_account_for_multiple_accounts(
    tmp_path, monkeypatch
):
    cfg, cfg_path = _cfg(tmp_path)
    monkeypatch.delenv("TASTYTRADE_ACCOUNT_NUMBER", raising=False)

    class _FakeClient:
        def list_accounts(self):
            return [
                BrokerAccount(account_number="5WT0001"),
                BrokerAccount(account_number="5WT0002"),
            ]

        def get_balances(self, account_number: str):
            return BrokerBalance(account_number=account_number, raw={"cash-balance": "1000.00"})

    try:
        run_tastytrade_live_session(
            cfg=cfg,
            config_path=cfg_path,
            output_dir=tmp_path / "paper",
            run_id="taste_run",
            client_builder=lambda _cfg: _FakeClient(),
        )
    except ValueError as exc:
        assert "Multiple Tastytrade accounts are available" in str(exc)
    else:
        raise AssertionError("Expected multiple-account selection failure")


def test_run_tastytrade_live_session_executes_native_cycle_when_enabled(tmp_path):
    cfg, cfg_path = _cfg_live_native(tmp_path)

    class _FakeClient:
        def list_accounts(self):
            return [BrokerAccount(account_number="5WT0001", authority_level="owner")]

        def get_balances(self, account_number: str):
            return BrokerBalance(account_number=account_number, raw={"cash-balance": "1000.00"})

        def get_market_quotes(self, symbols):
            return {str(symbol): {"bid": "1.11", "ask": "1.12"} for symbol in symbols}

        def submit_order(self, request):
            return {"id": f"ord_{request.symbol}", "status": "received"}

    def _native_strategy_runner(**_kwargs):
        return {
            "native_order_intents": [
                {"symbol": "EURUSD", "side": "buy", "quantity": 1.0},
                {"symbol": "GBPUSD", "side": "sell", "quantity": 1.0},
            ]
        }

    run_dir = run_tastytrade_live_session(
        cfg=cfg,
        config_path=cfg_path,
        output_dir=tmp_path / "native_cycle",
        run_id="taste_native",
        mode="live",
        client_builder=lambda _cfg: _FakeClient(),
        strategy_runner=_native_strategy_runner,
    )

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["broker_order_routing"] == "broker_native"
    assert manifest["broker_market_data_source"] == "tastytrade_api"
    assert manifest["runtime_toggles"]["broker_native_orders_enabled"] is True
    assert manifest["runtime_toggles"]["broker_market_data_enabled"] is True

    state = json.loads((run_dir / "session_state.json").read_text(encoding="utf-8"))
    assert state["broker_native_status"] == "completed"

    native_summary = json.loads((run_dir / "broker_native_summary.json").read_text(encoding="utf-8"))
    assert native_summary["market_data_source"] == "broker_api"
    assert native_summary["order_submission_mode"] == "broker_native"
    assert native_summary["orders_submitted"] == 2

    orders = (run_dir / "orders.parquet")
    assert orders.exists()

    events = [
        json.loads(line)
        for line in (run_dir / "broker_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(event["event"] == "broker_market_data_snapshot" for event in events)
    submitted = [event for event in events if event["event"] == "broker_order_submitted"]
    assert len(submitted) == 2
