import type {
  AlgoState,
  AnalysisResponse,
  PairsResponse,
  PaperOpsState,
  RegimeResponse,
  RunsResponse,
  WalkforwardResponse
} from './fx-types';

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to fetch ${url}: ${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

function withRunId(url: string, runId?: string | null): string {
  const trimmed = runId?.trim();
  if (!trimmed) {
    return url;
  }
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}runId=${encodeURIComponent(trimmed)}`;
}

export function fetchAlgoState(runId?: string | null): Promise<AlgoState> {
  return fetchJson<AlgoState>(withRunId('/api/state', runId));
}

export function fetchWalkforwardData(): Promise<WalkforwardResponse> {
  return fetchJson<WalkforwardResponse>('/api/walkforward');
}

export function fetchRegimeData(runId?: string | null): Promise<RegimeResponse> {
  return fetchJson<RegimeResponse>(withRunId('/api/regime', runId));
}

export function fetchPairsData(runId?: string | null): Promise<PairsResponse> {
  return fetchJson<PairsResponse>(withRunId('/api/pairs', runId));
}

export function fetchAnalysisData(runId?: string | null): Promise<AnalysisResponse> {
  return fetchJson<AnalysisResponse>(withRunId('/api/analysis', runId));
}

export function fetchPaperOps(runId?: string | null): Promise<PaperOpsState> {
  return fetchJson<PaperOpsState>(withRunId('/api/paper', runId));
}

export function fetchRuns(): Promise<RunsResponse> {
  return fetchJson<RunsResponse>('/api/runs');
}

export async function triggerAlgoRun(params?: Record<string, string>) {
  const res = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params ?? {})
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Run failed: ${text}`);
  }
  return res.json();
}
