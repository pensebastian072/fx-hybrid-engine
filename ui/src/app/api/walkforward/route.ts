import { NextResponse } from 'next/server';
import type {
  OpsEvent,
  PnlAttribution,
  PnlAttributionRow,
  PromotionDecision,
  ProofChecks,
  Robustness,
  WalkforwardMetrics,
  WalkforwardResponse
} from '@/lib/fx-types';
import { buildProvenance, resolveArtifactJson } from '@/lib/server-artifacts';

function toNumber(value: unknown): number | undefined {
  if (value === null || value === undefined || value === '') {
    return undefined;
  }
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function normalizeAttributionRows(rows: unknown): PnlAttributionRow[] {
  if (!Array.isArray(rows)) {
    return [];
  }

  return rows.map((row) => {
    const record = (row ?? {}) as Record<string, unknown>;
    return {
      ...record,
      engine_source:
        typeof record.engine_source === 'string' ? record.engine_source : undefined,
      entry_regime:
        typeof record.entry_regime === 'string' ? record.entry_regime : undefined,
      n_trades: toNumber(record.n_trades),
      total_pnl: toNumber(record.total_pnl),
      win_rate: toNumber(record.win_rate),
      pnl_share: toNumber(record.pnl_share),
      pnl_share_within_engine: toNumber(record.pnl_share_within_engine)
    };
  });
}

function normalizePnlAttribution(value: unknown): PnlAttribution | null {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const record = value as Record<string, unknown>;
  return {
    engine_x_regime: normalizeAttributionRows(record.engine_x_regime),
    by_engine: normalizeAttributionRows(record.by_engine),
    by_regime: normalizeAttributionRows(record.by_regime)
  };
}

export async function GET() {
  const walkforwardMetrics = resolveArtifactJson<WalkforwardMetrics>(
    'walkforward_metrics.json'
  );
  const pnlAttribution = resolveArtifactJson('pnl_attribution.json');
  const proofChecks = resolveArtifactJson<ProofChecks>('proof_checks.json');
  const promotionDecision =
    resolveArtifactJson<PromotionDecision>('promotion_decision.json');
  const robustness = resolveArtifactJson<Robustness>('robustness.json');
  const riskEvents = resolveArtifactJson<OpsEvent[]>('risk_events.json', {
    treatEmptyArrayAsMissing: true
  });

  const provenance = buildProvenance({
    walkforward_metrics: walkforwardMetrics.source,
    pnl_attribution: pnlAttribution.source,
    proof_checks: proofChecks.source,
    promotion_decision: promotionDecision.source,
    robustness: robustness.source,
    risk_events: riskEvents.source
  });

  const response: WalkforwardResponse = {
    source: provenance.overall,
    provenance,
    walkforward_metrics: walkforwardMetrics.data,
    pnl_attribution: normalizePnlAttribution(pnlAttribution.data),
    proof_checks: proofChecks.data,
    promotion_decision: promotionDecision.data,
    robustness: robustness.data,
    risk_events: riskEvents.data ?? []
  };

  return NextResponse.json(response);
}
