"""CLI entry points for fx-hybrid-engine."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fx_hybrid_engine.contracts import SCHEMA_VERSION
from fx_hybrid_engine.utils.identity import hash_config, make_run_id, resolve_git_commit


def _base_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--config", default="config/default.yaml", help="Path to YAML config file")
    p.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return p


def main_train() -> None:
    """Train HMM regime model and trend LogReg model."""
    from datetime import date, timedelta

    import numpy as np

    from fx_hybrid_engine.data.provider import fetch_multi_symbol
    from fx_hybrid_engine.engines.trend import TrendEngine
    from fx_hybrid_engine.features.indicators import momentum_slope, rolling_vol
    from fx_hybrid_engine.regime.hmm import RegimeHMM
    from fx_hybrid_engine.utils.config import load_config
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Train HMM and trend model on historical OpenBB data")
    p.add_argument("--years", type=int, default=None, help="Override history_years from config")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    cfg = load_config(args.config)
    years = args.years or cfg.data.history_years
    end = date.today()
    start = end - timedelta(days=365 * years)

    all_symbols = list({s for pair in cfg.pair_list for s in pair} | set(cfg.trend_symbols))
    print(f"Fetching {len(all_symbols)} symbols from {start} to {end}...")
    data = fetch_multi_symbol(
        all_symbols,
        start,
        end,
        provider=cfg.data.openbb_provider,
        frequency=cfg.data.bar_frequency,
        source=cfg.data.source,
        seed=cfg.robustness.random_seed,
    )

    if not data:
        print("ERROR: No data fetched. Check OpenBB provider config.", file=sys.stderr)
        sys.exit(1)

    # --- Train Trend model ---
    print("Training trend LogReg model...")
    trend = TrendEngine(cfg.trend)
    trend.train(data)
    trend.save_model(cfg.trend.model_path)
    print(f"Trend model saved to {cfg.trend.model_path}")

    # --- Train HMM ---
    print("Training HMM regime model...")
    hmm = RegimeHMM(n_states=cfg.regime.n_states)
    obs_list = []
    for df in data.values():
        if "close" not in df.columns or len(df) < cfg.regime.vol_window + 2:
            continue
        close = df["close"]
        vol = rolling_vol(close, window=cfg.regime.vol_window, annualize=True)
        mom = momentum_slope(close, window=cfg.regime.vol_window)
        import pandas as pd  # noqa: PLC0415
        obs = pd.DataFrame({"vol": vol, "mom": mom}).dropna()
        obs_list.append(obs.values)

    if obs_list:
        combined = np.vstack(obs_list)
        hmm.fit(combined)
        hmm.save(cfg.regime.model_path)
        print(f"HMM model saved to {cfg.regime.model_path}")
    else:
        print("WARNING: No observation data for HMM training")


def main_backtest() -> None:
    """Run a Lean backtest."""
    from fx_hybrid_engine.lean.lean_runner import run_backtest
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Run a Lean CLI backtest")
    p.add_argument("--project", default="lean_project", help="Path to Lean project dir")
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default="2023-12-31")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    result = run_backtest(args.project, config_path=args.config)
    print(f"Total Return: {result.total_return:.2%}")
    print(f"Sharpe:       {result.sharpe:.3f}")
    print(f"Max Drawdown: {result.max_drawdown:.2%}")
    print(f"Trades:       {result.trades}")


def main_regime() -> None:
    """Print current regime state for symbols."""
    from datetime import date, timedelta

    from fx_hybrid_engine.data.provider import fetch_multi_symbol
    from fx_hybrid_engine.regime.orchestrator import RegimeOrchestrator
    from fx_hybrid_engine.utils.config import load_config
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Inspect current regime state")
    p.add_argument("--symbol", nargs="+", default=None)
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    cfg = load_config(args.config)
    symbols = args.symbol or cfg.trend_symbols
    end = date.today()
    start = end - timedelta(days=90)
    data = fetch_multi_symbol(
        symbols,
        start,
        end,
        provider=cfg.data.openbb_provider,
        frequency=cfg.data.bar_frequency,
        source=cfg.data.source,
        seed=cfg.robustness.random_seed,
    )

    orchestrator = RegimeOrchestrator(cfg.regime, cfg.risk)
    if not orchestrator.load_model():
        print("WARNING: HMM model not found. Run fxhe-train first.")

    state = orchestrator.update_regime(data)
    print(f"Current regime: {state}")
    for label, prob in orchestrator.state_probabilities.items():
        print(f"  {label}: {prob:.3f}")


def main_live() -> None:
    """Start live/paper trading for the configured execution rail."""
    from fx_hybrid_engine.brokers.tastytrade_live import run_tastytrade_live_session
    from fx_hybrid_engine.lean.lean_runner import run_cloud_push
    from fx_hybrid_engine.utils.config import load_config
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Start live or paper trading for the configured broker rail")
    p.add_argument("--project", default="lean_project")
    p.add_argument("--paper", action="store_true", default=False, help="Force paper mode output layout")
    p.add_argument("--live", action="store_true", default=False, help="Force live mode output layout")
    p.add_argument("--run-id", default=None, help="Optional explicit run id for non-QC rails")
    p.add_argument("--output-dir", default=None, help="Explicit output directory for non-QC rails")
    p.add_argument("--run-seconds", type=int, default=0, help="Optional heartbeat duration for non-QC rails")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    if args.paper and args.live:
        print("ERROR: choose only one of --paper or --live", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(args.config)
    broker = str(cfg.live_execution.broker).strip().lower()
    if args.paper:
        mode = "paper"
    elif args.live:
        mode = "live"
    else:
        mode = cfg.ops.mode

    if broker == "quantconnect":
        print(f"Pushing project {args.project} to QuantConnect cloud...")
        run_cloud_push(args.project)
        print("Done. Start the live session from the QC dashboard.")
        return
    if broker == "tastytrade":
        rail = str(cfg.live_execution.rail).strip().lower()
        broker_native_requested = rail == "tastytrade_live"
        broker_native_blockers: list[str] = []
        if broker_native_requested and not bool(cfg.live_execution.enable_broker_native_orders):
            broker_native_blockers.append("live_execution.enable_broker_native_orders=false")
        if broker_native_requested and not bool(cfg.live_execution.enable_broker_market_data):
            broker_native_blockers.append("live_execution.enable_broker_market_data=false")
        if broker_native_blockers:
            print("ERROR: tastytrade_live rail is blocked by default-off Phase 3 gates.", file=sys.stderr)
            print("Set the following config flags to true before using tastytrade_live:", file=sys.stderr)
            for blocker in broker_native_blockers:
                print(f"  - {blocker}", file=sys.stderr)
            sys.exit(1)
        run_dir = run_tastytrade_live_session(
            cfg=cfg,
            config_path=args.config,
            run_id=args.run_id,
            output_dir=args.output_dir,
            mode=mode,
            run_seconds=args.run_seconds,
        )
        print(f"Tastytrade session initialized: {run_dir}")
        print("Run fxhe-live-precheck first and configure tastytrade.symbol_map before sending real orders.")
        return
    print(f"ERROR: unsupported live_execution.broker '{cfg.live_execution.broker}'", file=sys.stderr)
    sys.exit(1)


def main_local_paper() -> None:
    """Start a broker-agnostic local paper session that emits strategy artifacts."""
    from fx_hybrid_engine.ops.local_paper import run_local_paper_session
    from fx_hybrid_engine.utils.config import load_config
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Start a broker-agnostic local paper session")
    p.add_argument("--run-id", default=None, help="Optional explicit run id")
    p.add_argument("--output-dir", default=None, help="Explicit output directory")
    p.add_argument("--run-seconds", type=int, default=0, help="Optional heartbeat duration")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    cfg = load_config(args.config)
    run_dir = run_local_paper_session(
        cfg=cfg,
        config_path=args.config,
        run_id=args.run_id,
        output_dir=args.output_dir,
        run_seconds=args.run_seconds,
    )
    print(f"Local paper session initialized: {run_dir}")
    print("This path emits local-only paper artifacts and does not route broker orders.")


def main_walkforward() -> None:
    """Run the Phase 5 walk-forward pipeline and emit proof artifacts."""
    from fx_hybrid_engine.evaluation.walkforward import run_walkforward
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Run walk-forward evaluation and generate Phase 5 artifacts")
    p.add_argument("--run-id", default=None, help="Optional explicit walk-forward run id")
    p.add_argument("--max-splits", type=int, default=None, help="Optional split cap for smoke runs")
    p.add_argument("--no-report", action="store_true", help="Skip report generation")
    p.add_argument("--skip-robustness", action="store_true", help="Skip parameter robustness sweep")
    p.add_argument("--no-precompute", action="store_true", help="Disable split-level precomputed signal cache")
    p.add_argument("--no-mode-reuse", action="store_true", help="Disable shared precomputed stream reuse across modes")
    p.add_argument("--regime-compare", action="store_true", help="Force-enable regime comparison outputs")
    p.add_argument("--no-regime-compare", action="store_true", help="Force-disable regime comparison outputs")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    if args.regime_compare and args.no_regime_compare:
        print("ERROR: choose only one of --regime-compare or --no-regime-compare", file=sys.stderr)
        sys.exit(1)
    regime_compare_flag = None
    if args.regime_compare:
        regime_compare_flag = True
    elif args.no_regime_compare:
        regime_compare_flag = False

    run_dir = run_walkforward(
        config_path=args.config,
        wf_run_id=args.run_id,
        max_splits=args.max_splits,
        run_report=not args.no_report,
        skip_robustness=args.skip_robustness,
        precompute=not args.no_precompute,
        mode_reuse=not args.no_mode_reuse,
        run_regime_compare=regime_compare_flag,
    )
    print(f"Walk-forward run complete: {run_dir}")


def main_regime_compare() -> None:
    """Run walk-forward with regime comparison policies enabled."""
    from fx_hybrid_engine.evaluation.walkforward import run_walkforward
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Run regime comparison policies on walk-forward splits")
    p.add_argument("--run-id", default=None, help="Optional explicit run id")
    p.add_argument("--max-splits", type=int, default=None, help="Optional split cap")
    p.add_argument("--with-report", action="store_true", help="Also generate phase5 report")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    run_dir = run_walkforward(
        config_path=args.config,
        wf_run_id=args.run_id,
        max_splits=args.max_splits,
        run_report=args.with_report,
        skip_robustness=True,
        precompute=True,
        mode_reuse=True,
        run_regime_compare=True,
    )
    print(f"Regime comparison run complete: {run_dir}")


def main_phase1() -> None:
    """Run Phase 1 verification (smoke or verification profile)."""
    from fx_hybrid_engine.evaluation.phase1_runner import run_phase1
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Run Phase 1 data-loop verification runner")
    p.add_argument("--profile", default="smoke", choices=["smoke", "verification"])
    p.add_argument("--run-id", default=None, help="Optional explicit run id")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    run_dir = run_phase1(config_path=args.config, profile=args.profile, run_id=args.run_id)
    print(f"Phase 1 run complete: {run_dir}")


def main_build_trend_dataset() -> None:
    """Build reproducible trend dataset parquet + stats artifacts."""
    from fx_hybrid_engine.evaluation.trend_dataset import build_trend_dataset
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Build Stage 4 trend dataset artifact")
    p.add_argument("--run-id", default=None, help="Optional explicit dataset run id")
    p.add_argument("--output-dir", default=None, help="Optional explicit output directory")
    p.add_argument("--start", default=None, help="Override start date")
    p.add_argument("--end", default=None, help="Override end date")
    p.add_argument("--frequency", default=None, help="Override bar frequency")
    p.add_argument("--symbols", nargs="+", default=None, help="Optional symbol override")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    result = build_trend_dataset(
        config_path=args.config,
        output_dir=args.output_dir,
        run_id=args.run_id,
        symbols=args.symbols,
        start_date=args.start,
        end_date=args.end,
        frequency=args.frequency,
    )
    print(f"Dataset run dir:  {result['run_dir']}")
    print(f"Dataset parquet:  {result['dataset_path']}")
    print(f"Dataset stats:    {result['stats_path']}")
    print(f"Dataset rows:     {result['rows']}")
    print(f"Dataset data_hash:{result['data_hash']}")


def main_train_trend() -> None:
    """Train versioned trend model with walk-forward metrics artifacts."""
    from fx_hybrid_engine.evaluation.trend_training import train_trend_walkforward
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Train versioned Stage 4 trend model artifacts")
    p.add_argument("--model-version", default=None, help="Optional explicit model version")
    p.add_argument("--dataset-path", default=None, help="Optional existing trend_dataset.parquet path")
    p.add_argument("--output-root", default=None, help="Optional model root override")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    result = train_trend_walkforward(
        config_path=args.config,
        model_version=args.model_version,
        dataset_path=args.dataset_path,
        output_root=args.output_root,
    )
    print(f"Model version:    {result['model_version']}")
    print(f"Model dir:        {result['model_dir']}")
    print(f"Model artifact:   {result['model_path']}")
    print(f"Metadata:         {result['metadata_path']}")
    print(f"Split metrics:    {result['metrics_path']}")
    print(f"OOS summary:      {result['summary_path']}")


def main_validate_run() -> None:
    """Validate artifact contract for a walk-forward run directory."""
    from fx_hybrid_engine.evaluation.contract import render_issues, validate_run_tree
    from fx_hybrid_engine.utils.logging import setup_logging

    p = argparse.ArgumentParser(description="Validate walk-forward run artifact contract")
    p.add_argument("--run-dir", required=True, help="Path to artifacts/walkforward/<wf_run_id>")
    p.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    ok, issues = validate_run_tree(args.run_dir)
    if issues:
        print(render_issues(issues))
    if ok:
        print("Validation passed.")
        return
    print("Validation failed.", file=sys.stderr)
    sys.exit(1)


def main_report() -> None:
    """Generate Phase 5 proof markdown/json report from a run directory."""
    from fx_hybrid_engine.reporting.phase5_report import generate_phase5_report
    from fx_hybrid_engine.utils.config import load_config
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Generate Phase 5 proof report from walk-forward artifacts")
    p.add_argument("--wf-run-id", default=None, help="Walk-forward run id under configured output_root")
    p.add_argument("--run-dir", default=None, help="Direct path to run directory (overrides --wf-run-id)")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        if not args.wf_run_id:
            print("ERROR: provide --run-dir or --wf-run-id", file=sys.stderr)
            sys.exit(1)
        cfg = load_config(args.config)
        run_dir = Path(cfg.walkforward.output_root) / args.wf_run_id

    md_path, json_path = generate_phase5_report(run_dir)
    print(f"Report generated: {md_path}")
    print(f"Summary JSON:     {json_path}")


def main_verify_parity() -> None:
    """Verify metric parity across two walk-forward runs."""
    from fx_hybrid_engine.evaluation.parity import verify_parity
    from fx_hybrid_engine.utils.logging import setup_logging

    p = argparse.ArgumentParser(description="Verify walk-forward parity across two run directories")
    p.add_argument("--run-a", required=True, help="Path to first run directory")
    p.add_argument("--run-b", required=True, help="Path to second run directory")
    p.add_argument(
        "--profile",
        default="local_smoke",
        choices=["local_smoke", "external", "openbb"],
        help="Parity profile controls default epsilon threshold",
    )
    p.add_argument("--epsilon", type=float, default=None, help="Override absolute epsilon threshold")
    p.add_argument("--out", default=None, help="Output JSON path (default: <run-a>/parity_report.json)")
    p.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    report = verify_parity(
        run_a=args.run_a,
        run_b=args.run_b,
        profile=args.profile,
        epsilon=args.epsilon,
        output_path=args.out,
    )
    print(f"Parity report: {report['output_path']}")
    print(f"Parity pass:   {report['pass']}")
    if not bool(report["pass"]):
        print("Parity verification failed.", file=sys.stderr)
        sys.exit(1)


def _empty_stream_frames(run_id: str) -> dict[str, object]:
    import pandas as pd

    ts = datetime.now(UTC).isoformat()
    return {
        "bars": pd.DataFrame(columns=["timestamp", "run_id", "symbol", "open", "high", "low", "close"]),
        "features": pd.DataFrame(columns=["timestamp", "run_id", "symbol"]),
        "signals": pd.DataFrame(columns=["timestamp", "run_id", "symbol", "engine_source"]),
        "targets": pd.DataFrame(columns=["timestamp", "run_id", "symbol", "target_weight"]),
        "orders": pd.DataFrame(columns=["timestamp", "run_id", "symbol", "order_type"]),
        "fills": pd.DataFrame(columns=["timestamp", "run_id", "symbol", "fill_price"]),
        "equity_curve": pd.DataFrame(columns=["timestamp", "run_id", "equity"]),
        "risk_events": pd.DataFrame(
            [
                {"timestamp": ts, "run_id": run_id, "reason": "session_initialized"},
            ]
        ),
    }


def main_paper_session() -> None:
    """Bootstrap a paper-session run directory and initialize append-only streams."""
    from fx_hybrid_engine.data.providers.factory import create_provider
    from fx_hybrid_engine.ops.ladder import normalize_stage, resolve_ladder_caps
    from fx_hybrid_engine.ops.layout import build_run_dir
    from fx_hybrid_engine.ops.storage import (
        append_bars,
        append_broker_events,
        append_equity_curve,
        append_features,
        append_fills,
        append_orders,
        append_reconciliation_events,
        append_risk_events,
        append_signals,
        append_targets,
        initialize_run_metadata,
    )
    from fx_hybrid_engine.utils.config import load_config
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Bootstrap a paper/live operational run directory")
    p.add_argument("--run-id", default=None, help="Optional explicit run id")
    p.add_argument("--mode", default=None, help="Mode name for output layout (default from config)")
    p.add_argument("--output-dir", default=None, help="Explicit output directory (overrides layout builder)")
    p.add_argument("--run-seconds", type=int, default=0, help="Optional heartbeat loop duration")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    cfg = load_config(args.config)
    mode = args.mode or cfg.ops.mode
    cfg_payload = asdict(cfg)
    cfg_hash = hash_config(cfg_payload)
    now = datetime.now(UTC)
    run_id = args.run_id or make_run_id(now, cfg_hash)
    run_dir = Path(args.output_dir) if args.output_dir else build_run_dir(cfg.ops.output_root, mode=mode, run_id=run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    all_symbols = sorted(list({s for pair in cfg.pair_list for s in pair} | set(cfg.trend_symbols)))
    provider = create_provider(cfg.data.source, openbb_provider=cfg.data.openbb_provider, seed=cfg.robustness.random_seed)
    if not provider.supports_frequency(cfg.data.bar_frequency):
        raise ValueError(
            f"Configured data.source '{cfg.data.source}' does not support bar frequency '{cfg.data.bar_frequency}'"
        )
    manifest = {
        "run_id": run_id,
        "mode": mode,
        "config_path": str(Path(args.config).resolve()),
        "git_commit": resolve_git_commit(),
        "config_hash": cfg_hash,
        "schema_version": SCHEMA_VERSION,
        "seed": int(cfg.robustness.random_seed),
        "bar_frequency": cfg.data.bar_frequency,
        "data_source": cfg.data.source,
        "live_rail": cfg.live_execution.rail,
        "live_broker": cfg.live_execution.broker,
        "symbols": all_symbols,
        "startup_time_utc": now.isoformat(),
        "runtime_toggles": {
            "precompute_enabled": None,
            "mode_reuse_enabled": None,
        },
        "ladder_stage": normalize_stage(cfg.micro_live_ladder.active_stage),
        "ladder_caps": asdict(resolve_ladder_caps(stage=cfg.micro_live_ladder.active_stage)),
    }
    initialize_run_metadata(run_dir, run_manifest=manifest, config_snapshot={"config": cfg_payload})

    frames = _empty_stream_frames(run_id)
    append_bars(run_dir, frames["bars"], run_id=run_id)
    append_features(run_dir, frames["features"], run_id=run_id)
    append_signals(run_dir, frames["signals"], run_id=run_id)
    append_targets(run_dir, frames["targets"], run_id=run_id)
    append_orders(run_dir, frames["orders"], run_id=run_id)
    append_fills(run_dir, frames["fills"], run_id=run_id)
    append_equity_curve(run_dir, frames["equity_curve"], run_id=run_id)
    append_risk_events(run_dir, frames["risk_events"], run_id=run_id)
    append_reconciliation_events(run_dir, [], run_id=run_id)
    append_broker_events(
        run_dir,
        [
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "event": "session_start",
                "symbols": all_symbols,
                "bar_frequency": cfg.data.bar_frequency,
                "data_source": cfg.data.source,
                "rail": cfg.live_execution.rail,
                "broker": cfg.live_execution.broker,
            }
        ],
        run_id=run_id,
    )

    print(f"Paper session run initialized: {run_dir}")
    print(f"Subscribed symbols: {all_symbols}")
    print(f"Bar timeframe: {cfg.data.bar_frequency}")

    state_path = run_dir / "session_state.json"
    existing_state: dict[str, object] = {}
    if state_path.exists():
        try:
            existing_state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing_state = {}
    session_state = {
        "run_id": run_id,
        "status": "running",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "cooldowns": existing_state.get("cooldowns", {}),
        "disabled_pairs": existing_state.get("disabled_pairs", []),
        "pair_state": existing_state.get("pair_state", {}),
        "disabled_until_scan": existing_state.get("disabled_until_scan", {}),
        "last_regime": existing_state.get("last_regime", "UNKNOWN"),
    }
    state_path.write_text(json.dumps(session_state, indent=2), encoding="utf-8")

    status = "stopped"
    try:
        if args.run_seconds > 0:
            end = time.time() + args.run_seconds
            while time.time() < end:
                time.sleep(1)
                append_broker_events(
                    run_dir,
                    [{"event": "heartbeat", "run_id": run_id, "timestamp": datetime.now(UTC).isoformat()}],
                    run_id=run_id,
                )
    except KeyboardInterrupt:
        status = "interrupted"
    finally:
        session_state["status"] = status
        session_state["ended_at_utc"] = datetime.now(UTC).isoformat()
        state_path.write_text(
            json.dumps(session_state, indent=2),
            encoding="utf-8",
        )
        append_broker_events(
            run_dir,
            [
                {
                    "event": "session_stop",
                    "run_id": run_id,
                    "status": status,
                    "rail": cfg.live_execution.rail,
                    "broker": cfg.live_execution.broker,
                }
            ],
            run_id=run_id,
        )
    print(f"Session final state written: {state_path}")


def main_phase6_precheck() -> None:
    """Run strict Phase 6 completion precheck gates on an ops run directory."""
    from fx_hybrid_engine.ops.precheck import run_phase6_precheck
    from fx_hybrid_engine.utils.config import load_config
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Run strict Phase 6 precheck on operational artifacts")
    p.add_argument("--run-dir", required=True, help="Ops run directory")
    p.add_argument("--docs-path", default="docs/OPERATIONS.md", help="Runbook path")
    p.add_argument("--no-strict-full", action="store_true", help="Skip scenario harness checks")
    p.add_argument("--rail", default=None, help="Operational rail target (default from config)")
    p.add_argument("--paper-window-days", type=int, default=None, help="Window for paper telemetry checks")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    cfg = load_config(args.config)
    rail = args.rail or cfg.live_execution.rail

    json_path, md_path, ok = run_phase6_precheck(
        args.run_dir,
        config_path=args.config,
        docs_path=args.docs_path,
        strict_full=not args.no_strict_full,
        rail=rail,
        paper_window_days=args.paper_window_days,
    )
    print(f"Precheck JSON: {json_path}")
    print(f"Precheck MD:   {md_path}")
    print(f"Precheck pass: {ok}")
    if not ok:
        sys.exit(1)


def main_weekly_eval() -> None:
    """Run scheduled weekly evaluation and emit ladder decision JSON."""
    from fx_hybrid_engine.evaluation.weekly_eval import run_weekly_evaluation
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Run weekly evaluation (walk-forward + report + ladder decision)")
    p.add_argument("--run-id", default=None, help="Optional explicit run id")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    run_dir, decision = run_weekly_evaluation(config_path=args.config, run_id=args.run_id)
    print(f"Weekly evaluation run: {run_dir}")
    print(f"Decision JSON:         {decision}")


def main_promote_check() -> None:
    """Run promotion gate checks using Phase 5 proof + paper telemetry."""
    from fx_hybrid_engine.ops.promote_check import run_promotion_check
    from fx_hybrid_engine.utils.config import load_config
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Run promotion check and emit promotion_decision.json")
    p.add_argument("--wf-id", default=None, help="Walkforward run id under configured output root")
    p.add_argument("--wf-run-dir", default=None, help="Direct walkforward run directory")
    p.add_argument("--paper-run-dir", required=True, help="Paper run directory for telemetry")
    p.add_argument("--window-days", type=int, default=None, help="Paper telemetry lookback window")
    p.add_argument("--out", default=None, help="Output JSON path override")
    p.add_argument("--fail-on-no-go", action="store_true", help="Exit non-zero when promotion check fails")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    cfg = load_config(args.config)
    if args.wf_run_dir:
        wf_run_dir = Path(args.wf_run_dir)
    else:
        if not args.wf_id:
            print("ERROR: provide --wf-run-dir or --wf-id", file=sys.stderr)
            sys.exit(1)
        wf_run_dir = Path(cfg.walkforward.output_root) / args.wf_id

    decision, out_path = run_promotion_check(
        cfg=cfg,
        wf_run_dir=wf_run_dir,
        paper_run_dir=args.paper_run_dir,
        window_days=args.window_days,
        output_path=args.out,
    )
    print(f"Promotion decision: {out_path}")
    print(f"Promotion pass:     {decision['pass']}")
    if args.fail_on_no_go and not bool(decision["pass"]):
        sys.exit(1)


def main_live_precheck() -> None:
    """Run live deployment precheck gates for the configured live rail."""
    from fx_hybrid_engine.ops.live_precheck import run_live_precheck
    from fx_hybrid_engine.utils.config import load_config
    from fx_hybrid_engine.utils.logging import setup_logging

    p = _base_parser("Run live precheck before deployment")
    p.add_argument("--out", default=None, help="Output report path")
    args = p.parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    cfg = load_config(args.config)
    report, path = run_live_precheck(cfg=cfg, output_path=args.out)
    print(f"Live precheck report: {path}")
    print(f"Live precheck rail:   {report['rail']}")
    print(f"Live precheck broker: {report['broker']}")
    print(f"Live precheck pass:   {report['pass']}")
    if not bool(report["pass"]):
        sys.exit(1)
