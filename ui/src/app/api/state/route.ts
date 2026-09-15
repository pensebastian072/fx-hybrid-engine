import { NextRequest, NextResponse } from 'next/server';
import type {
  AlgoState,
  Candle,
  EquityPoint,
  OpsEvent,
  RunManifest,
  Trade
} from '@/lib/fx-types';
import {
  artifactExists,
  buildProvenance,
  resolveRunContext,
  resolveArtifactJson
} from '@/lib/server-artifacts';

export async function GET(req: NextRequest) {
  try {
    const runId = req.nextUrl.searchParams.get('runId');
    const runContext = resolveRunContext(runId);
    const effectiveRunId = runContext.requested_run_found
      ? runContext.effective_run_id
      : null;
    const manifest = resolveArtifactJson<RunManifest>('manifest.json', {
      runId: effectiveRunId
    });
    const trades = resolveArtifactJson<Trade[]>('trades.json', {
      runId: effectiveRunId
    });
    const candles = resolveArtifactJson<Candle[]>('candles.json', {
      runId: effectiveRunId,
      treatEmptyArrayAsMissing: true
    });
    const equityCurve = resolveArtifactJson<EquityPoint[]>('equity_curve.json', {
      runId: effectiveRunId
    });
    const events = resolveArtifactJson<OpsEvent[]>('events.json', {
      runId: effectiveRunId,
      treatEmptyArrayAsMissing: true
    });

    if (!manifest.data) {
      return NextResponse.json(
        { error: 'No manifest.json found in latest_run or mock directories' },
        { status: 404 }
      );
    }

    const provenance = buildProvenance({
      manifest: manifest.source,
      trades: trades.source,
      candles: candles.source,
      equity_curve: equityCurve.source,
      events: events.source
    });

    const state: AlgoState = {
      manifest: manifest.data,
      trades: trades.data ?? [],
      candles: candles.data ?? [],
      equity_curve: equityCurve.data ?? [],
      events: events.data ?? [],
      run_context: runContext,
      source: provenance.overall,
      provenance,
      log_available: artifactExists('run.log', { runId: effectiveRunId })
    };

    return NextResponse.json(state);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
