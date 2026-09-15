import { NextRequest, NextResponse } from 'next/server';
import type {
  EngineAllocation,
  RegimePosterior,
  RegimeResponse
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
  const regimePosteriors = resolveArtifactJson<RegimePosterior[]>(
    'regime_posteriors.json',
    { runId: effectiveRunId, treatEmptyArrayAsMissing: true }
  );
  const engineAllocations = resolveArtifactJson<EngineAllocation[]>(
    'engine_allocations.json',
    { runId: effectiveRunId, treatEmptyArrayAsMissing: true }
  );

  const provenance = buildProvenance({
    regime_posteriors: regimePosteriors.source,
    engine_allocations: engineAllocations.source
  });

  const response: RegimeResponse = {
    run_context: runContext,
    source: provenance.overall,
    provenance,
    regime_posteriors: regimePosteriors.data ?? [],
    engine_allocations: engineAllocations.data ?? []
  };

  return NextResponse.json(response);
}
