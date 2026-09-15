import { spawnSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import type {
  ArtifactSource,
  BrokerContextSummary,
  DataProvenance,
  RunContext,
  RunCatalogEntry
} from './fx-types';

export const PROJECT_ROOT = path.resolve(process.cwd(), '..');
export const LATEST_RUN_DIR = path.join(PROJECT_ROOT, 'artifacts', 'latest_run');
export const MOCK_DIR = path.join(PROJECT_ROOT, 'artifacts', 'mock');
export const OUTPUTS_PAPER_DIR = path.join(PROJECT_ROOT, 'outputs', 'paper');
export const RUN_HISTORY_DIR = path.join(PROJECT_ROOT, 'artifacts', 'run_history');

function safeMtimeMs(filePath: string): number {
  try {
    return fs.statSync(filePath).mtimeMs;
  } catch {
    return 0;
  }
}

function resolveNormalizedRunDir(runDir: string): string {
  return path.join(RUN_HISTORY_DIR, path.basename(runDir));
}

function ensureNormalizedRunHistory(runDir: string): string | null {
  const normalizedDir = resolveNormalizedRunDir(runDir);
  const manifestPath = path.join(normalizedDir, 'manifest.json');
  const shouldRefresh =
    !fs.existsSync(manifestPath) || safeMtimeMs(manifestPath) < safeMtimeMs(runDir);

  if (shouldRefresh) {
    fs.mkdirSync(normalizedDir, { recursive: true });
    const normalizeScript = path.join(PROJECT_ROOT, 'scripts', 'normalize_artifacts.py');
    const result = spawnSync(
      'python',
      [normalizeScript, '--paper-run-dir', runDir, '--out-dir', normalizedDir],
      {
        cwd: PROJECT_ROOT,
        encoding: 'utf-8',
        windowsHide: true
      }
    );

    if (result.status !== 0 && !fs.existsSync(manifestPath)) {
      return null;
    }
  }

  return fs.existsSync(normalizedDir) ? normalizedDir : null;
}

function readJson<T>(filePath: string): T | null {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function isUsable<T>(value: T | null, treatEmptyArrayAsMissing: boolean): value is T {
  if (value === null) {
    return false;
  }
  if (treatEmptyArrayAsMissing && Array.isArray(value) && value.length === 0) {
    return false;
  }
  return true;
}

function safeEntries(dirPath: string): fs.Dirent[] {
  try {
    return fs.readdirSync(dirPath, { withFileTypes: true });
  } catch {
    return [];
  }
}

function safeTimestamp(value: unknown): string | null {
  if (typeof value !== 'string' || value.trim() === '') {
    return null;
  }
  const millis = Date.parse(value);
  return Number.isNaN(millis) ? null : value;
}

function timestampMs(value: string | null): number {
  if (!value) {
    return 0;
  }
  const millis = Date.parse(value);
  return Number.isNaN(millis) ? 0 : millis;
}

function countArrayFile(filePath: string): number {
  const payload = readJson<unknown[]>(filePath);
  return Array.isArray(payload) ? payload.length : 0;
}

function listPaperRunDirs(): string[] {
  if (!fs.existsSync(OUTPUTS_PAPER_DIR)) {
    return [];
  }

  const runDirs: string[] = [];
  for (const dateEntry of safeEntries(OUTPUTS_PAPER_DIR)) {
    if (!dateEntry.isDirectory()) {
      continue;
    }
    const dateDir = path.join(OUTPUTS_PAPER_DIR, dateEntry.name);
    for (const runEntry of safeEntries(dateDir)) {
      if (!runEntry.isDirectory()) {
        continue;
      }
      const runDir = path.join(dateDir, runEntry.name);
      if (
        fs.existsSync(path.join(runDir, 'run_manifest.json')) ||
        fs.existsSync(path.join(runDir, 'manifest.json')) ||
        fs.existsSync(path.join(runDir, 'session_state.json'))
      ) {
        runDirs.push(runDir);
      }
    }
  }
  return runDirs;
}

function normalizeBrokerContext(raw: unknown): BrokerContextSummary | null {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const payload = raw as Record<string, unknown>;
  return {
    provider: typeof payload.provider === 'string' ? payload.provider : undefined,
    available: Boolean(payload.available),
    connection_status:
      typeof payload.connection_status === 'string'
        ? payload.connection_status
        : 'unknown',
    account_number:
      typeof payload.account_number === 'string' ? payload.account_number : null,
    symbol_map_ready_count:
      typeof payload.symbol_map_ready_count === 'number'
        ? payload.symbol_map_ready_count
        : undefined,
    symbol_map_missing: Array.isArray(payload.symbol_map_missing)
      ? payload.symbol_map_missing.filter(
          (value): value is string => typeof value === 'string' && value.length > 0
        )
      : undefined,
    positions_count:
      typeof payload.positions_count === 'number' ? payload.positions_count : undefined,
    open_orders_count:
      typeof payload.open_orders_count === 'number'
        ? payload.open_orders_count
        : undefined,
    accounts_count:
      typeof payload.accounts_count === 'number' ? payload.accounts_count : undefined,
    balances:
      payload.balances && typeof payload.balances === 'object'
        ? (payload.balances as Record<string, unknown>)
        : null,
    positions: Array.isArray(payload.positions)
      ? payload.positions.filter(
          (value): value is { symbol: string; quantity: number } =>
            !!value &&
            typeof value === 'object' &&
            typeof (value as Record<string, unknown>).symbol === 'string' &&
            typeof (value as Record<string, unknown>).quantity === 'number'
        )
      : undefined,
    open_orders: Array.isArray(payload.open_orders)
      ? payload.open_orders.filter(
          (value): value is Record<string, unknown> =>
            !!value && typeof value === 'object' && !Array.isArray(value)
        )
      : undefined,
    error: typeof payload.error === 'string' ? payload.error : null
  };
}

function buildRunCatalogEntry(runDir: string): RunCatalogEntry {
  const runManifest = readJson<Record<string, unknown>>(
    path.join(runDir, 'run_manifest.json')
  );
  const uiManifest = readJson<Record<string, unknown>>(path.join(runDir, 'manifest.json'));
  const sessionState = readJson<Record<string, unknown>>(
    path.join(runDir, 'session_state.json')
  );
  const strategySummary = readJson<Record<string, unknown>>(
    path.join(runDir, 'paper_strategy_summary.json')
  );
  const paperOps = readJson<Record<string, unknown>>(path.join(runDir, 'paper_ops.json'));
  const brokerContextLatest = normalizeBrokerContext(
    readJson<Record<string, unknown>>(path.join(runDir, 'broker_context_latest.json'))
  );
  const paperOpsBrokerContext = normalizeBrokerContext(paperOps?.broker_context);
  const brokerContext = brokerContextLatest ?? paperOpsBrokerContext;

  const runId =
    (typeof runManifest?.run_id === 'string' && runManifest.run_id) ||
    (typeof uiManifest?.run_id === 'string' && uiManifest.run_id) ||
    path.basename(runDir);
  const startedAt =
    safeTimestamp(runManifest?.startup_time_utc) ||
    safeTimestamp(sessionState?.started_at_utc) ||
    safeTimestamp(uiManifest?.started_at);
  const endedAt =
    safeTimestamp(sessionState?.ended_at_utc) || safeTimestamp(uiManifest?.ended_at);
  const symbols = Array.isArray(runManifest?.symbols)
    ? runManifest.symbols.filter(
        (value): value is string => typeof value === 'string' && value.length > 0
      )
    : Array.isArray(uiManifest?.symbols)
      ? uiManifest.symbols.filter(
          (value): value is string => typeof value === 'string' && value.length > 0
        )
      : [];
  const noTradeSummary =
    paperOps?.no_trade_summary && typeof paperOps.no_trade_summary === 'object'
      ? (paperOps.no_trade_summary as Record<string, unknown>)
      : null;
  const strategyStatus =
    (typeof strategySummary?.status === 'string' && strategySummary.status) ||
    (typeof sessionState?.paper_strategy_status === 'string' &&
      sessionState.paper_strategy_status) ||
    null;
  const fillCount =
    (typeof strategySummary?.fills_emitted === 'number' && strategySummary.fills_emitted) ||
    (typeof noTradeSummary?.fills_emitted === 'number' && noTradeSummary.fills_emitted) ||
    countArrayFile(path.join(runDir, 'paper_trades.json'));
  const tradeCount =
    (typeof strategySummary?.closed_trades === 'number' && strategySummary.closed_trades) ||
    (typeof noTradeSummary?.closed_trades === 'number' && noTradeSummary.closed_trades) ||
    countArrayFile(path.join(runDir, 'trades.json'));
  const signalCount =
    (typeof strategySummary?.signals_emitted === 'number' && strategySummary.signals_emitted) ||
    (typeof noTradeSummary?.signals_emitted === 'number' && noTradeSummary.signals_emitted) ||
    countArrayFile(path.join(runDir, 'signals_sample.json'));
  const safetySummary =
    strategySummary?.safety_summary && typeof strategySummary.safety_summary === 'object'
      ? (strategySummary.safety_summary as Record<string, unknown>)
      : null;

  return {
    run_id: runId,
    started_at: startedAt,
    ended_at: endedAt,
    status:
      (typeof sessionState?.status === 'string' && sessionState.status) ||
      (typeof uiManifest?.status === 'string' && uiManifest.status) ||
      'unknown',
    strategy_status: strategyStatus,
    artifact_context: strategySummary ? 'paper_strategy' : 'paper_scaffold',
    symbols,
    last_regime:
      (typeof strategySummary?.last_regime === 'string' && strategySummary.last_regime) ||
      (typeof sessionState?.last_regime === 'string' && sessionState.last_regime) ||
      (typeof uiManifest?.regime === 'string' && uiManifest.regime) ||
      null,
    signal_count: signalCount,
    fill_count: fillCount,
    trade_count: tradeCount,
    close_only: Boolean(
      safetySummary?.close_only ??
        sessionState?.close_only ??
        uiManifest?.close_only ??
        noTradeSummary?.close_only_active
    ),
    data_source:
      (typeof strategySummary?.data_source === 'string' && strategySummary.data_source) ||
      (typeof runManifest?.data_source === 'string' && runManifest.data_source) ||
      (typeof uiManifest?.data_profile === 'string' && uiManifest.data_profile) ||
      null,
    live_broker:
      typeof runManifest?.live_broker === 'string' ? runManifest.live_broker : null,
    live_rail: typeof runManifest?.live_rail === 'string' ? runManifest.live_rail : null,
    broker_order_routing:
      (typeof strategySummary?.broker_order_routing === 'string' &&
        strategySummary.broker_order_routing) ||
      (typeof uiManifest?.broker_order_routing === 'string' &&
        uiManifest.broker_order_routing) ||
      null,
    broker_context: brokerContext
  };
}

export function listPaperRuns(): RunCatalogEntry[] {
  return listPaperRunDirs()
    .map((runDir) => buildRunCatalogEntry(runDir))
    .sort((left, right) => {
      const leftSort = Math.max(
        timestampMs(left.ended_at),
        timestampMs(left.started_at)
      );
      const rightSort = Math.max(
        timestampMs(right.ended_at),
        timestampMs(right.started_at)
      );
      return rightSort - leftSort;
    });
}

export function resolveRunDir(runId: string): string | null {
  const trimmed = runId.trim();
  if (!trimmed) {
    return null;
  }

  for (const runDir of listPaperRunDirs()) {
    if (path.basename(runDir) === trimmed) {
      return runDir;
    }
    const manifest = readJson<Record<string, unknown>>(path.join(runDir, 'run_manifest.json'));
    if (typeof manifest?.run_id === 'string' && manifest.run_id === trimmed) {
      return runDir;
    }
  }

  return null;
}

function resolveRunIdFromDir(runDir: string): string {
  const runManifest = readJson<Record<string, unknown>>(
    path.join(runDir, 'run_manifest.json')
  );
  if (typeof runManifest?.run_id === 'string' && runManifest.run_id.trim()) {
    return runManifest.run_id;
  }

  const normalizedDir = ensureNormalizedRunHistory(runDir);
  if (normalizedDir) {
    const normalizedManifest = readJson<Record<string, unknown>>(
      path.join(normalizedDir, 'manifest.json')
    );
    if (
      typeof normalizedManifest?.run_id === 'string' &&
      normalizedManifest.run_id.trim()
    ) {
      return normalizedManifest.run_id;
    }
  }

  return path.basename(runDir);
}

function resolveLatestKnownRunId(): string | null {
  const latestManifest = readJson<Record<string, unknown>>(
    path.join(LATEST_RUN_DIR, 'manifest.json')
  );
  if (
    typeof latestManifest?.run_id === 'string' &&
    latestManifest.run_id.trim()
  ) {
    return latestManifest.run_id;
  }

  const latestRun = listPaperRuns()[0];
  return latestRun?.run_id ?? null;
}

export function resolveRunContext(requestedRunId?: string | null): RunContext {
  const trimmed = requestedRunId?.trim() ?? '';
  if (!trimmed) {
    return {
      requested_run_id: null,
      effective_run_id: null,
      requested_run_found: false,
      fallback_applied: false
    };
  }

  const runDir = resolveRunDir(trimmed);
  if (runDir) {
    return {
      requested_run_id: trimmed,
      effective_run_id: resolveRunIdFromDir(runDir),
      requested_run_found: true,
      fallback_applied: false
    };
  }

  return {
    requested_run_id: trimmed,
    effective_run_id: resolveLatestKnownRunId(),
    requested_run_found: false,
    fallback_applied: true
  };
}

export function resolveArtifactJson<T>(
  filename: string,
  options: {
    fallbackToMock?: boolean;
    treatEmptyArrayAsMissing?: boolean;
    runId?: string | null;
  } = {}
): { data: T | null; source: ArtifactSource } {
  const {
    fallbackToMock = true,
    treatEmptyArrayAsMissing = false,
    runId
  } = options;
  const trimmedRunId = typeof runId === 'string' ? runId.trim() : '';

  if (trimmedRunId) {
    const runDir = resolveRunDir(trimmedRunId);
    if (!runDir) {
      return { data: null, source: 'missing' };
    }

    const normalizedRunDir = ensureNormalizedRunHistory(runDir);
    const selected = normalizedRunDir
      ? readJson<T>(path.join(normalizedRunDir, filename))
      : readJson<T>(path.join(runDir, filename));
    if (isUsable(selected, treatEmptyArrayAsMissing)) {
      return { data: selected, source: 'run_history' };
    }

    const direct = readJson<T>(path.join(runDir, filename));
    if (isUsable(direct, treatEmptyArrayAsMissing)) {
      return { data: direct, source: 'run_history' };
    }

    return { data: null, source: 'missing' };
  }

  const latest = readJson<T>(path.join(LATEST_RUN_DIR, filename));
  if (isUsable(latest, treatEmptyArrayAsMissing)) {
    return { data: latest, source: 'latest_run' };
  }

  if (fallbackToMock) {
    const mock = readJson<T>(path.join(MOCK_DIR, filename));
    if (isUsable(mock, treatEmptyArrayAsMissing)) {
      return { data: mock, source: 'mock' };
    }
  }

  return { data: null, source: 'missing' };
}

export function buildProvenance(files: Record<string, ArtifactSource>): DataProvenance {
  const values = Object.values(files);
  const overall =
    values.length > 0 && values.every((value) => value === 'latest_run')
      ? 'latest_run'
      : values.length > 0 && values.every((value) => value === 'run_history')
        ? 'run_history'
        : values.length > 0 && values.every((value) => value === 'mock')
          ? 'mock'
          : 'mixed';

  return {
    overall,
    files
  };
}

export function artifactExists(
  filename: string,
  options: { runId?: string | null; includeMock?: boolean } = {}
): boolean {
  const { runId, includeMock = false } = options;
  const trimmedRunId = typeof runId === 'string' ? runId.trim() : '';

  if (trimmedRunId) {
    const runDir = resolveRunDir(trimmedRunId);
    if (!runDir) {
      return false;
    }
    const normalizedRunDir = ensureNormalizedRunHistory(runDir);
    return (
      !!normalizedRunDir && fs.existsSync(path.join(normalizedRunDir, filename))
    ) || fs.existsSync(path.join(runDir, filename));
  }

  if (fs.existsSync(path.join(LATEST_RUN_DIR, filename))) {
    return true;
  }
  return includeMock && fs.existsSync(path.join(MOCK_DIR, filename));
}
