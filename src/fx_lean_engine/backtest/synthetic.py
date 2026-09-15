"""Synthetic deterministic smoke backtest for CI."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from fx_lean_engine.config import load_backtest_config, load_universe_config
from fx_lean_engine.data.consolidation import BarRouter
from fx_lean_engine.orchestration.pipeline import build_runtime_from_configs
from fx_lean_engine.types import Bar


def _price_paths(symbols: list[str], steps: int, seed: int = 42) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    paths: dict[str, np.ndarray] = {}
    for idx, symbol in enumerate(symbols):
        start = 1.0 + idx * 0.1
        drift = 0.00002 * (1 if idx % 2 == 0 else -1)
        noise = rng.normal(0.0, 0.0008 + idx * 0.00005, size=steps)
        values = np.empty(steps, dtype=float)
        values[0] = start
        for i in range(1, steps):
            values[i] = max(values[i - 1] * (1.0 + drift + noise[i]), 1e-3)
        paths[symbol] = values
    return paths


def _safe_git_sha(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _build_phase1_review(
    run_id: str,
    symbols: list[str],
    resolution: str,
    start: str,
    end: str,
    metrics: dict[str, object],
    warnings: list[str],
) -> str:
    warn_lines = [f"- {item}" for item in warnings] if warnings else ["- none"]
    lines = [
        f"# Phase 1 Review: {run_id}",
        "",
        "## Run Setup",
        f"- symbols: {', '.join(symbols)}",
        f"- resolution: {resolution}",
        "- consolidated_interval_minutes: 15",
        f"- timeframe: {start} to {end}",
        "",
        "## Key Metrics",
        f"- trades_count: {metrics.get('trades_count', 0)}",
        f"- turnover: {metrics.get('turnover', 0.0)}",
        f"- avg_holding_bars: {metrics.get('avg_holding_bars', 0.0)}",
        f"- max_gross_exposure: {metrics.get('max_gross_exposure', 0.0)}",
        "",
        "## Failures and Warnings",
        *warn_lines,
    ]
    return "\n".join(lines) + "\n"


def _build_phase2_demo_report(run_id: str, pair_rows: list[dict[str, object]]) -> str:
    sorted_rows = sorted(pair_rows, key=lambda row: float(row.get("pct_time_tradable", 0.0)), reverse=True)
    lines = [
        f"# Phase 2 Demo Report: {run_id}",
        "",
        "## Top Tradable Pairs",
    ]
    if not sorted_rows:
        lines.append("- none")
    else:
        for row in sorted_rows[:5]:
            lines.append(
                "- "
                + f"{row.get('pair', '')}: tradable_pct={float(row.get('pct_time_tradable', 0.0)):.3f}, "
                + f"disable_events={int(row.get('disable_events', 0))}, "
                + f"reenable_events={int(row.get('reenable_events', 0))}"
            )
    return "\n".join(lines) + "\n"


def run_synthetic_backtest(
    output_dir: str | Path,
    config_dir: str | Path | None = None,
    backtest_config_name: str = "backtest_smoke.yaml",
) -> Path:
    """Run deterministic synthetic smoke and persist artifact contract."""
    project_root = Path(__file__).resolve().parents[3]
    cfg_root = Path(config_dir) if config_dir is not None else project_root / "configs"
    backtest_config_path = cfg_root / str(backtest_config_name)
    run_cfg = load_backtest_config(backtest_config_path)
    universe_cfg = load_universe_config(cfg_root / "universe.yaml")

    steps = 2400  # enough bars to warm all engines with 15m consolidation
    start_ts = datetime.fromisoformat(run_cfg.start_date).replace(tzinfo=UTC)

    symbols = run_cfg.symbols if run_cfg.symbols else list(universe_cfg.pairs or [])
    if len(symbols) == 1:
        for fallback in ("GBPUSD", "AUDUSD"):
            if fallback not in symbols:
                symbols.append(fallback)

    runtime = build_runtime_from_configs(cfg_root, active_symbols=symbols, pairs_lookback_override=60)

    prices = _price_paths(symbols=symbols, steps=steps)

    router = BarRouter(interval_minutes=universe_cfg.consolidated_bar_minutes)
    for symbol in symbols:
        router.register(symbol, runtime.on_consolidated_bar)

    for i in range(steps):
        ts = start_ts + timedelta(minutes=i)
        for symbol in symbols:
            close = float(prices[symbol][i])
            open_px = float(prices[symbol][max(i - 1, 0)])
            high = max(open_px, close) * 1.0002
            low = min(open_px, close) * 0.9998
            router.on_minute_bar(
                Bar(
                    symbol=symbol,
                    start=ts,
                    end=ts + timedelta(minutes=1),
                    open=open_px,
                    high=high,
                    low=low,
                    close=close,
                    volume=1000.0,
                )
            )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    run_id = f"synthetic_{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}"
    runtime.artifacts.pnl_by_pair = runtime.build_pair_pnl_rows()
    if runtime.runtime_cfg.phase2_pairs_gating_enabled and not runtime.artifacts.pair_state_events:
        status_map = runtime._validity_manager.get_status_map()  # noqa: SLF001
        runtime.artifacts.pair_state_events = [
            {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "pair": f"{pair[0]}-{pair[1]}",
                "event": "STATUS_SNAPSHOT",
                "from": "",
                "to": str(status),
                "reason": "NO_TRANSITION_DURING_RUN",
            }
            for pair, status in sorted(status_map.items())
        ]
        if not runtime.artifacts.pair_state_events:
            runtime.artifacts.pair_state_events = [
                {
                    "timestamp": datetime.now(tz=UTC).isoformat(),
                    "pair": "",
                    "event": "STATUS_SNAPSHOT",
                    "from": "",
                    "to": "WATCH",
                    "reason": "NO_ELIGIBLE_PAIRS",
                }
            ]

    _write_csv(out_dir / "signals.csv", runtime.artifacts.signals)
    _write_csv(out_dir / "orders.csv", runtime.artifacts.orders)
    _write_csv(out_dir / "equity_curve.csv", runtime.artifacts.equity_curve)
    _write_csv(out_dir / "regime.csv", runtime.artifacts.regime)
    _write_csv(out_dir / "features.csv", runtime.artifacts.features)
    _write_csv(out_dir / "targets.csv", runtime.artifacts.targets)
    _write_csv(out_dir / "bar_health.csv", runtime.artifacts.bar_health)
    _write_csv(out_dir / "risk_events.csv", runtime.artifacts.risk_events)
    _write_csv(out_dir / "pairs_candidates.csv", runtime.artifacts.pairs_candidates)
    _write_csv(out_dir / "pairs_scan.csv", runtime.artifacts.pairs_scan)
    _write_csv(out_dir / "pair_state_events.csv", runtime.artifacts.pair_state_events)
    _write_csv(out_dir / "pnl_by_pair.csv", runtime.artifacts.pnl_by_pair)

    if runtime.artifacts.bars:
        _write_csv(out_dir / "bars.csv", runtime.artifacts.bars)
    if runtime.artifacts.fills:
        _write_csv(out_dir / "fills.csv", runtime.artifacts.fills)
    if runtime.artifacts.broker_events:
        _write_csv(out_dir / "broker_events.csv", runtime.artifacts.broker_events)

    if runtime.artifacts.regime_posteriors:
        _write_csv(out_dir / "regime_posteriors.csv", runtime.artifacts.regime_posteriors)
    if runtime.artifacts.regime_events:
        _write_csv(out_dir / "regime_events.csv", runtime.artifacts.regime_events)
    if runtime.artifacts.regime_hmm_params is not None:
        (out_dir / "regime_hmm_params.json").write_text(
            json.dumps(runtime.artifacts.regime_hmm_params, indent=2),
            encoding="utf-8",
        )
    if runtime.artifacts.regime_state_map is not None:
        (out_dir / "regime_state_map.json").write_text(
            json.dumps(runtime.artifacts.regime_state_map, indent=2),
            encoding="utf-8",
        )

    metrics = runtime.build_metrics(
        run_id=run_id,
        start=run_cfg.start_date,
        end=run_cfg.end_date,
        resolution=universe_cfg.subscription_resolution,
    )
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    config_files = {
        "universe": cfg_root / "universe.yaml",
        "pairs": cfg_root / "pairs.yaml",
        "runtime": cfg_root / "runtime.yaml",
        "pairs_policy": cfg_root / "pairs_policy.yaml",
        "pairs_overrides": cfg_root / "pairs_overrides.yaml",
        "regime": cfg_root / "regime.yaml",
        "backtest": backtest_config_path,
    }
    config_hashes = {
        name: _sha256(path)
        for name, path in config_files.items()
        if path.exists()
    }

    run_manifest = {
        "run_id": run_id,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "git_sha": _safe_git_sha(project_root),
        "runtime_mode": runtime.runtime_cfg.execution_mode,
        "data_source": runtime.runtime_cfg.data_source,
        "config_hashes": config_hashes,
        "config_files": {name: str(path) for name, path in config_files.items() if path.exists()},
    }
    (out_dir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")

    config_snapshot = {
        "universe": asdict(universe_cfg),
        "pairs": asdict(runtime.pairs_cfg),
        "runtime": asdict(runtime.runtime_cfg),
        "pairs_policy": asdict(runtime.pairs_policy_cfg),
        "regime": asdict(runtime.regime_cfg),
        "backtest": asdict(run_cfg),
    }
    (out_dir / "config_snapshot.yaml").write_text(yaml.safe_dump(config_snapshot, sort_keys=False), encoding="utf-8")

    summary = {
        "run_id": run_id,
        "status": "completed",
        "data_source": "synthetic",
        "start": run_cfg.start_date,
        "end": run_cfg.end_date,
        "symbol_count": len(symbols),
        "signals_rows": len(runtime.artifacts.signals),
        "orders_rows": len(runtime.artifacts.orders),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    warnings: list[str] = []
    if runtime.artifacts.bar_health:
        warnings.extend([f"bar_health:{row.get('event_type', '')}" for row in runtime.artifacts.bar_health])
    if runtime.artifacts.risk_events:
        warnings.extend([f"risk:{row.get('reason', '')}" for row in runtime.artifacts.risk_events])
    (out_dir / "phase1_review.md").write_text(
        _build_phase1_review(
            run_id=run_id,
            symbols=symbols,
            resolution=universe_cfg.subscription_resolution,
            start=run_cfg.start_date,
            end=run_cfg.end_date,
            metrics=metrics,
            warnings=warnings,
        ),
        encoding="utf-8",
    )
    (out_dir / "phase2_demo_report.md").write_text(
        _build_phase2_demo_report(run_id=run_id, pair_rows=runtime.artifacts.pnl_by_pair),
        encoding="utf-8",
    )

    return out_dir
