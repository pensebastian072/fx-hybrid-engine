"""Live deployment precheck gates for safe QC launch."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from fx_hybrid_engine.brokers.tastytrade import (
    TastytradeApiClient,
    TastytradeApiError,
    TastytradeCredentials,
)
from fx_hybrid_engine.ops.ladder import load_ladder_policy, normalize_stage, resolve_ladder_caps
from fx_hybrid_engine.ops.model_registry import refresh_due
from fx_hybrid_engine.utils.config import EngineConfig, TastytradeConfig


def _required_env_vars(cfg: EngineConfig) -> list[str]:
    broker = str(cfg.live_execution.broker).strip().lower()
    if broker == "tastytrade":
        required = [
            cfg.tastytrade.client_id_env,
            cfg.tastytrade.client_secret_env,
            cfg.tastytrade.refresh_token_env,
            *cfg.live_precheck.extra_required_env_vars,
        ]
    else:
        required = [*cfg.live_precheck.required_env_vars, *cfg.live_precheck.extra_required_env_vars]
    deduped: list[str] = []
    for item in required:
        key = str(item).strip()
        if key and key not in deduped:
            deduped.append(key)
    return deduped


def _expected_symbols(cfg: EngineConfig) -> list[str]:
    return sorted({s for pair in cfg.pair_list for s in pair} | set(cfg.trend_symbols))


def _missing_symbol_map(cfg: EngineConfig) -> list[str]:
    if str(cfg.live_execution.broker).strip().lower() != "tastytrade" or not cfg.tastytrade.require_symbol_map:
        return []
    missing = []
    for symbol in _expected_symbols(cfg):
        mapped = str(cfg.tastytrade.symbol_map.get(symbol, "")).strip()
        if not mapped:
            missing.append(symbol)
    return missing


def _build_tastytrade_client(cfg: TastytradeConfig) -> TastytradeApiClient:
    creds = TastytradeCredentials(
        client_id=os.environ[cfg.client_id_env],
        client_secret=os.environ[cfg.client_secret_env],
        refresh_token=os.environ[cfg.refresh_token_env],
    )
    return TastytradeApiClient(
        credentials=creds,
        oauth_token_url=cfg.oauth_token_url,
        accounts_url=cfg.accounts_url,
        balances_url_template=cfg.balances_url_template,
    )


def _broker_native_gate_state(cfg: EngineConfig, *, broker: str, rail: str) -> tuple[bool, list[str]]:
    broker_native_requested = broker == "tastytrade" and rail == "tastytrade_live"
    blockers: list[str] = []
    if broker_native_requested and not bool(cfg.live_execution.enable_broker_native_orders):
        blockers.append("enable_broker_native_orders_disabled")
    if broker_native_requested and not bool(cfg.live_execution.enable_broker_market_data):
        blockers.append("enable_broker_market_data_disabled")
    return broker_native_requested, blockers


def _run_tastytrade_checks(cfg: EngineConfig, *, missing_env: list[str]) -> tuple[dict[str, bool], dict[str, object]]:
    details: dict[str, object] = {
        "account_env_var": cfg.tastytrade.account_number_env,
        "symbol_map": cfg.tastytrade.symbol_map,
    }
    missing_map = _missing_symbol_map(cfg)
    checks = {
        "symbol_map_complete": len(missing_map) == 0,
        "broker_api_reachable": False,
        "broker_account_accessible": False,
    }
    details["missing_symbol_map"] = missing_map
    selected_account = os.getenv(cfg.tastytrade.account_number_env)
    details["selected_account"] = selected_account

    if missing_env or not cfg.tastytrade.validate_api_on_precheck:
        if not cfg.tastytrade.validate_api_on_precheck:
            checks["broker_api_reachable"] = True
            checks["broker_account_accessible"] = not bool(cfg.tastytrade.require_account_number and not selected_account)
        return checks, details

    client = _build_tastytrade_client(cfg.tastytrade)
    accounts = client.list_accounts()
    account_numbers = [account.account_number for account in accounts]
    details["account_numbers"] = account_numbers
    checks["broker_api_reachable"] = True

    resolved_account = selected_account
    if not resolved_account and len(account_numbers) == 1:
        resolved_account = account_numbers[0]
    details["resolved_account"] = resolved_account
    if cfg.tastytrade.require_account_number and not selected_account:
        return checks, details
    if resolved_account and resolved_account in account_numbers:
        client.get_balances(resolved_account)
        checks["broker_account_accessible"] = True
    return checks, details


def run_live_precheck(
    *,
    cfg: EngineConfig,
    output_path: str | Path | None = None,
) -> tuple[dict[str, object], Path]:
    """Validate env, stage risk caps, emergency controls, and model freshness."""
    broker = str(cfg.live_execution.broker).strip().lower()
    rail = str(cfg.live_execution.rail).strip() or "qc_paper"
    required_env = _required_env_vars(cfg)
    missing_env = [name for name in required_env if not os.getenv(name)]
    ladder_policy = load_ladder_policy(cfg.live_precheck.ladder_config_path)
    current_stage = normalize_stage(cfg.micro_live_ladder.active_stage)
    caps = resolve_ladder_caps(stage=current_stage, ladder_policy=ladder_policy)
    risk_caps_match_stage = (
        cfg.risk.max_leverage > 0
        and caps.max_gross_exposure > 0
        and caps.max_gross_exposure <= cfg.risk.max_leverage
        and caps.per_symbol_risk_cap > 0
        and caps.per_symbol_risk_cap <= caps.max_gross_exposure
        and caps.max_open_positions > 0
    )
    broker_native_requested, broker_native_blockers = _broker_native_gate_state(
        cfg,
        broker=broker,
        rail=rail,
    )
    due = refresh_due(cfg.model_registry)
    models_fresh = not any(bool(v) for v in due.values())
    ops_doc = Path("docs/OPERATIONS.md")
    has_emergency_flatten = False
    if ops_doc.exists():
        try:
            has_emergency_flatten = "emergency flatten" in ops_doc.read_text(encoding="utf-8").lower()
        except Exception:  # noqa: BLE001
            has_emergency_flatten = False

    checks = {
        "env_vars_present": len(missing_env) == 0,
        "ladder_caps_valid": caps.max_gross_exposure > 0 and caps.per_symbol_risk_cap > 0 and caps.max_open_positions > 0,
        "risk_caps_match_resolved_stage": risk_caps_match_stage,
        "emergency_flatten_available": (has_emergency_flatten if cfg.live_precheck.require_emergency_flatten else True),
        "models_fresh": models_fresh,
        "broker_native_orders_enabled_for_requested_rail": "enable_broker_native_orders_disabled" not in broker_native_blockers,
        "broker_market_data_enabled_for_requested_rail": "enable_broker_market_data_disabled" not in broker_native_blockers,
    }
    broker_details: dict[str, object] = {}
    if broker == "tastytrade":
        try:
            broker_checks, broker_details = _run_tastytrade_checks(cfg, missing_env=missing_env)
        except TastytradeApiError as exc:
            broker_checks = {
                "symbol_map_complete": len(_missing_symbol_map(cfg)) == 0,
                "broker_api_reachable": False,
                "broker_account_accessible": False,
            }
            broker_details = {"error": str(exc)}
        checks.update(broker_checks)
    report = {
        "pass": all(bool(v) for v in checks.values()),
        "checks": checks,
        "rail": rail,
        "broker": broker,
        "required_env_vars": required_env,
        "missing_env_vars": missing_env,
        "current_stage": current_stage,
        "resolved_caps": asdict(caps),
        "risk_max_leverage": float(cfg.risk.max_leverage),
        "model_refresh_due": due,
        "operations_doc_path": str(ops_doc),
        "broker_native_requested": broker_native_requested,
        "broker_native_blockers": broker_native_blockers,
        "broker_native_flags": {
            "enable_broker_native_orders": bool(cfg.live_execution.enable_broker_native_orders),
            "enable_broker_market_data": bool(cfg.live_execution.enable_broker_market_data),
        },
        "broker_details": broker_details,
    }
    out = Path(output_path) if output_path else Path("artifacts") / "live_precheck_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report, out
