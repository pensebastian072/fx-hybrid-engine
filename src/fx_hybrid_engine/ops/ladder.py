"""Micro-live ladder policy and promotion decision helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from fx_hybrid_engine.utils.config import LadderStageConfig, MicroLiveLadderConfig

CANONICAL_STAGE_ORDER = ("stage0_paper", "stage1_micro", "stage2_small", "stage3_scale")
LEGACY_ALIAS_MAP = {
    "stage_1": "stage1_micro",
    "stage_2": "stage2_small",
    "stage_3": "stage3_scale",
}


@dataclass(frozen=True, slots=True)
class LadderCaps:
    stage: str
    max_gross_exposure: float
    per_symbol_risk_cap: float
    max_open_positions: int
    breaker_loss_multiplier: float


def normalize_stage(stage: str) -> str:
    key = str(stage).strip().lower()
    if key in LEGACY_ALIAS_MAP:
        return LEGACY_ALIAS_MAP[key]
    if key in CANONICAL_STAGE_ORDER:
        return key
    return "stage0_paper"


def get_stage_config(cfg: MicroLiveLadderConfig, stage: str | None = None) -> LadderStageConfig:
    selected = normalize_stage(stage or cfg.active_stage)
    if selected == "stage0_paper":
        return cfg.stage0_paper
    if selected == "stage1_micro":
        return cfg.stage1_micro
    if selected == "stage2_small":
        return cfg.stage2_small
    return cfg.stage3_scale


def load_ladder_policy(path: str | Path = "config/ladder.yaml") -> dict[str, object]:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    if not isinstance(raw, dict):
        raw = {}
    aliases = dict(LEGACY_ALIAS_MAP)
    aliases.update({str(k): str(v) for k, v in (raw.get("aliases") or {}).items()})
    stages = raw.get("stages") or {}
    active = normalize_stage(str(raw.get("active_stage", "stage0_paper")))
    return {
        "active_stage": active,
        "stages": stages,
        "aliases": aliases,
    }


def resolve_ladder_caps(
    *,
    stage: str,
    ladder_policy: dict[str, object] | None = None,
) -> LadderCaps:
    policy = ladder_policy or load_ladder_policy()
    aliases = {**LEGACY_ALIAS_MAP, **{str(k): str(v) for k, v in (policy.get("aliases") or {}).items()}}
    normalized = aliases.get(str(stage), str(stage))
    normalized = normalize_stage(normalized)
    stages = policy.get("stages") or {}
    if not isinstance(stages, dict):
        stages = {}
    payload = stages.get(normalized) or {}
    if not isinstance(payload, dict):
        payload = {}
    return LadderCaps(
        stage=normalized,
        max_gross_exposure=float(payload.get("max_gross_exposure", 1.0)),
        per_symbol_risk_cap=float(payload.get("per_symbol_risk_cap", 0.20)),
        max_open_positions=int(payload.get("max_open_positions", 12)),
        breaker_loss_multiplier=float(payload.get("breaker_loss_multiplier", 1.0)),
    )


def decide_ladder_action(
    current_stage: str,
    *,
    final_go: bool,
    severe_fail: bool = False,
) -> dict[str, str]:
    stage = normalize_stage(current_stage)
    idx = CANONICAL_STAGE_ORDER.index(stage)
    if final_go:
        next_idx = min(idx + 1, len(CANONICAL_STAGE_ORDER) - 1)
        action = "promote" if next_idx > idx else "hold"
    elif severe_fail:
        next_idx = max(idx - 1, 0)
        action = "demote" if next_idx < idx else "hold"
    else:
        next_idx = idx
        action = "hold"
    return {
        "action": action,
        "current_stage": stage,
        "next_stage": CANONICAL_STAGE_ORDER[next_idx],
    }

