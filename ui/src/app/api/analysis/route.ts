import { NextRequest, NextResponse } from 'next/server';
import type {
  AnalysisResponse,
  IndicatorSnapshot,
  SignalRow,
  TradeAnalysis,
  TrendDecision,
  TrendModelMeta
} from '@/lib/fx-types';
import {
  buildProvenance,
  resolveArtifactJson,
  resolveRunContext
} from '@/lib/server-artifacts';

export async function GET(req: NextRequest) {
  const runId = req.nextUrl.searchParams.get('runId');
  const runContext = resolveRunContext(runId);
  const effectiveRunId = runContext.requested_run_found
    ? runContext.effective_run_id
    : null;
  const analysis = resolveArtifactJson<TradeAnalysis>('trade_analysis.json', {
    runId: effectiveRunId
  });
  const signalsSample = resolveArtifactJson<SignalRow[]>('signals_sample.json', {
    runId: effectiveRunId,
    treatEmptyArrayAsMissing: true
  });
  const trendModelMeta = resolveArtifactJson<TrendModelMeta>(
    'trend_model_meta.json',
    { runId: effectiveRunId }
  );
  const trendDecisions = resolveArtifactJson<TrendDecision[]>('trend_decisions.json', {
    runId: effectiveRunId,
    treatEmptyArrayAsMissing: true
  });
  const indicatorSnapshots = resolveArtifactJson<IndicatorSnapshot[]>(
    'indicator_snapshots.json',
    {
      runId: effectiveRunId,
      treatEmptyArrayAsMissing: true
    }
  );

  const provenance = buildProvenance({
    analysis: analysis.source,
    signals_sample: signalsSample.source,
    trend_model_meta: trendModelMeta.source,
    trend_decisions: trendDecisions.source,
    indicator_snapshots: indicatorSnapshots.source
  });

  const response: AnalysisResponse = {
    run_context: runContext,
    source: provenance.overall,
    provenance,
    analysis: analysis.data,
    signals_sample: signalsSample.data ?? [],
    trend_model_meta: trendModelMeta.data,
    trend_decisions: trendDecisions.data ?? [],
    indicator_snapshots: indicatorSnapshots.data ?? []
  };

  return NextResponse.json(response);
}
