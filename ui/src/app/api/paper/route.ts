import { NextRequest, NextResponse } from 'next/server';
import type { PaperOpsState } from '@/lib/fx-types';
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
  const paperOps = resolveArtifactJson<
    Omit<PaperOpsState, 'run_context' | 'source' | 'provenance'>
  >(
    'paper_ops.json',
    { runId: effectiveRunId }
  );

  if (!paperOps.data) {
    return NextResponse.json(
      { error: 'No paper_ops.json found in latest_run or mock directories' },
      { status: 404 }
    );
  }

  const provenance = buildProvenance({
    paper_ops: paperOps.source
  });

  const response: PaperOpsState = {
    ...paperOps.data,
    run_context: runContext,
    source: provenance.overall,
    provenance
  };

  return NextResponse.json(response);
}
