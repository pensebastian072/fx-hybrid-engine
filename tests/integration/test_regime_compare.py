"""Integration smoke for regime comparison outputs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from fx_hybrid_engine.evaluation.walkforward import run_walkforward

pytestmark = pytest.mark.integration


def test_regime_compare_outputs_exist(tmp_path):
    cfg = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    cfg["walkforward"]["output_root"] = str(tmp_path / "artifacts")
    cfg["walkforward"]["data_profile"] = "local_smoke"
    cfg["walkforward"]["start_date"] = "2021-01-01"
    cfg["walkforward"]["end_date"] = "2021-12-31"
    cfg["walkforward"]["train_window_days"] = 120
    cfg["walkforward"]["test_window_days"] = 30
    cfg["walkforward"]["step_days"] = 30
    cfg["walkforward"]["max_splits"] = 1
    cfg["robustness"]["param_sweep_samples"] = 0
    cfg["regime_compare"]["enabled"] = True
    cfg_path = tmp_path / "regime_compare.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    run_dir = run_walkforward(
        config_path=cfg_path,
        wf_run_id="itest_regime_compare",
        max_splits=1,
        run_report=False,
        skip_robustness=True,
        precompute=True,
        mode_reuse=True,
        run_regime_compare=True,
    )
    assert (run_dir / "regime_comparison_metrics.csv").exists()
    assert (run_dir / "regime_comparison_report.md").exists()
    df = pd.read_csv(run_dir / "regime_comparison_metrics.csv")
    assert not df.empty
    assert {"hmm", "heuristic", "none"} <= set(df["policy"].astype(str))
