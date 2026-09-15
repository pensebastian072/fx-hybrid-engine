"""Brokerage model helpers for LEAN runtime modes."""

from __future__ import annotations

from typing import Any

from fx_lean_engine.config.models import RuntimeConfig


def apply_brokerage_model(algorithm: Any, runtime_cfg: RuntimeConfig) -> None:
    """Apply OANDA brokerage model when running inside LEAN."""
    if not hasattr(algorithm, "SetBrokerageModel"):
        return

    brokerage_name = None
    account_type = None
    try:
        from AlgorithmImports import AccountType, BrokerageName  # type: ignore

        brokerage_name = getattr(BrokerageName, "OandaBrokerage", None)
        account_type = getattr(AccountType, "Margin", None)
    except Exception:
        brokerage_name = getattr(getattr(algorithm, "BrokerageName", None), "OandaBrokerage", None)
        account_type = getattr(getattr(algorithm, "AccountType", None), "Margin", None)

    if runtime_cfg.account_type == "cash":
        try:
            from AlgorithmImports import AccountType  # type: ignore

            account_type = getattr(AccountType, "Cash", account_type)
        except Exception:
            account_type = getattr(getattr(algorithm, "AccountType", None), "Cash", account_type)

    if brokerage_name is None or account_type is None:
        return
    algorithm.SetBrokerageModel(brokerage_name, account_type)
