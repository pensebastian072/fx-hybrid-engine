import { NextRequest, NextResponse } from 'next/server';
import type { PairDiagnostic, PairHistory, PairsResponse } from '@/lib/fx-types';
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
  const pairs = resolveArtifactJson<PairDiagnostic[]>('pairs_diagnostics.json', {
    runId: effectiveRunId,
    treatEmptyArrayAsMissing: true
  });
  const pairHistory = resolveArtifactJson<Record<string, PairHistory>>(
    'pair_history.json',
    { runId: effectiveRunId }
  );

  const provenance = buildProvenance({
    pairs: pairs.source,
    pair_history: pairHistory.source
  });

  const response: PairsResponse = {
    run_context: runContext,
    source: provenance.overall,
    provenance,
    pairs: pairs.data ?? [],
    pair_history: pairHistory.data ?? {}
  };

  return NextResponse.json(response);
}
