from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fx_hybrid_engine.cli import main_live, main_local_paper


def _write_cfg(
    tmp_path: Path,
    *,
    broker: str,
    rail: str,
    enable_broker_native_orders: bool = False,
    enable_broker_market_data: bool = False,
) -> Path:
    raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    raw["live_execution"]["broker"] = broker
    raw["live_execution"]["rail"] = rail
    raw["live_execution"]["enable_broker_native_orders"] = enable_broker_native_orders
    raw["live_execution"]["enable_broker_market_data"] = enable_broker_market_data
    raw["tastytrade"]["symbol_map"] = {
        "AUDUSD": "6A",
        "EURUSD": "6E",
        "GBPUSD": "6B",
        "USDJPY": "6J",
        "USDCHF": "6S",
        "NZDUSD": "6N",
        "USDCAD": "6C",
    }
    cfg_path = tmp_path / f"{broker}.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return cfg_path


def test_main_live_dispatches_tastytrade(monkeypatch, tmp_path, capsys):
    cfg_path = _write_cfg(tmp_path, broker="tastytrade", rail="tastytrade_paper")
    calls: dict[str, object] = {}

    def _fake_session(**kwargs):
        calls.update(kwargs)
        return tmp_path / "taste_run"

    monkeypatch.setattr(
        "fx_hybrid_engine.brokers.tastytrade_live.run_tastytrade_live_session",
        _fake_session,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["fxhe-live", "--config", str(cfg_path), "--paper", "--run-id", "taste_cli"],
    )

    main_live()

    captured = capsys.readouterr()
    assert calls["run_id"] == "taste_cli"
    assert calls["mode"] == "paper"
    assert "Tastytrade session initialized" in captured.out


def test_main_live_blocks_tastytrade_live_when_phase3_flags_disabled(monkeypatch, tmp_path, capsys):
    cfg_path = _write_cfg(tmp_path, broker="tastytrade", rail="tastytrade_live")

    monkeypatch.setattr(
        "sys.argv",
        ["fxhe-live", "--config", str(cfg_path), "--live", "--run-id", "taste_cli"],
    )

    with pytest.raises(SystemExit) as exc:
        main_live()

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "tastytrade_live rail is blocked" in captured.err
    assert "enable_broker_native_orders" in captured.err
    assert "enable_broker_market_data" in captured.err


def test_main_live_dispatches_tastytrade_live_when_phase3_flags_enabled(monkeypatch, tmp_path, capsys):
    cfg_path = _write_cfg(
        tmp_path,
        broker="tastytrade",
        rail="tastytrade_live",
        enable_broker_native_orders=True,
        enable_broker_market_data=True,
    )
    calls: dict[str, object] = {}

    def _fake_session(**kwargs):
        calls.update(kwargs)
        return tmp_path / "taste_live_run"

    monkeypatch.setattr(
        "fx_hybrid_engine.brokers.tastytrade_live.run_tastytrade_live_session",
        _fake_session,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["fxhe-live", "--config", str(cfg_path), "--live", "--run-id", "taste_live_cli"],
    )

    main_live()

    captured = capsys.readouterr()
    assert calls["run_id"] == "taste_live_cli"
    assert calls["mode"] == "live"
    assert "Tastytrade session initialized" in captured.out


def test_main_live_dispatches_quantconnect(monkeypatch, tmp_path, capsys):
    cfg_path = _write_cfg(tmp_path, broker="quantconnect", rail="qc_paper")
    calls: dict[str, object] = {}

    def _fake_push(project: str):
        calls["project"] = project

    monkeypatch.setattr("fx_hybrid_engine.lean.lean_runner.run_cloud_push", _fake_push)
    monkeypatch.setattr(
        "sys.argv",
        ["fxhe-live", "--config", str(cfg_path), "--project", "qc_proj"],
    )

    main_live()

    captured = capsys.readouterr()
    assert calls["project"] == "qc_proj"
    assert "QuantConnect cloud" in captured.out


def test_main_local_paper_dispatches_shared_runner(monkeypatch, tmp_path, capsys):
    cfg_path = _write_cfg(tmp_path, broker="quantconnect", rail="qc_paper")
    calls: dict[str, object] = {}

    def _fake_session(**kwargs):
        calls.update(kwargs)
        return tmp_path / "local_paper_run"

    monkeypatch.setattr(
        "fx_hybrid_engine.ops.local_paper.run_local_paper_session",
        _fake_session,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fxhe-local-paper",
            "--config",
            str(cfg_path),
            "--run-id",
            "local_cli",
            "--run-seconds",
            "15",
        ],
    )

    main_local_paper()

    captured = capsys.readouterr()
    assert calls["run_id"] == "local_cli"
    assert calls["run_seconds"] == 15
    assert "Local paper session initialized" in captured.out
