import { NextRequest, NextResponse } from 'next/server';
import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import type { RunResult } from '@/lib/fx-types';

const PROJECT_ROOT = path.resolve(process.cwd(), '..');
const LATEST_RUN_DIR = path.join(PROJECT_ROOT, 'artifacts', 'latest_run');
const ALLOWED_EXECUTION_PROFILES = new Set(['local_paper', 'scaffold', 'qc_push']);

function parseRunFlag(value: unknown): boolean {
  return String(value ?? '').trim().toLowerCase() === 'true';
}

function parseBoundedInt(
  value: unknown,
  options: {
    field: string;
    min: number;
    max: number;
  }
): { ok: true; value: number } | { ok: false; error: string } {
  const { field, min, max } = options;
  if (value === undefined || value === null || String(value).trim() === '') {
    return { ok: true, value: min };
  }
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed)) {
    return { ok: false, error: `${field} must be an integer.` };
  }
  if (parsed < min || parsed > max) {
    return { ok: false, error: `${field} must be between ${min} and ${max}.` };
  }
  return { ok: true, value: parsed };
}

function resolveSafeConfigPath(value: unknown): { ok: true; value: string } | { ok: false; error: string } {
  const raw = String(value ?? 'config/default.yaml').trim();
  if (!raw) {
    return { ok: false, error: 'configPath cannot be empty.' };
  }
  if (raw.includes('\0')) {
    return { ok: false, error: 'configPath contains invalid characters.' };
  }
  if (path.isAbsolute(raw)) {
    return { ok: false, error: 'configPath must be a project-relative path.' };
  }
  const normalized = path.normalize(raw).replace(/\\/g, '/');
  if (normalized.startsWith('../') || normalized.includes('/../')) {
    return { ok: false, error: 'configPath cannot traverse outside the project.' };
  }
  if (!(normalized.startsWith('config/') || normalized.startsWith('configs/'))) {
    return { ok: false, error: 'configPath must be under config/ or configs/.' };
  }
  if (!normalized.endsWith('.yaml') && !normalized.endsWith('.yml')) {
    return { ok: false, error: 'configPath must be a YAML file.' };
  }
  const fullPath = path.join(PROJECT_ROOT, normalized);
  if (!fs.existsSync(fullPath)) {
    return { ok: false, error: `configPath not found: ${normalized}` };
  }
  return { ok: true, value: normalized };
}

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as Record<string, unknown>;

    const executionProfile = String(body.executionProfile ?? 'local_paper').trim();
    if (!ALLOWED_EXECUTION_PROFILES.has(executionProfile)) {
      return NextResponse.json(
        {
          status: 'error',
          exit_code: -1,
          stdout: '',
          stderr: `Unsupported executionProfile: ${executionProfile}`,
          duration_ms: 0
        },
        { status: 400 }
      );
    }

    const configPath = resolveSafeConfigPath(body.configPath);
    if (!configPath.ok) {
      return NextResponse.json(
        {
          status: 'error',
          exit_code: -1,
          stdout: '',
          stderr: configPath.error,
          duration_ms: 0
        },
        { status: 400 }
      );
    }

    const maxSplits = parseBoundedInt(body.maxSplits, {
      field: 'maxSplits',
      min: 1,
      max: 20
    });
    if (!maxSplits.ok) {
      return NextResponse.json(
        {
          status: 'error',
          exit_code: -1,
          stdout: '',
          stderr: maxSplits.error,
          duration_ms: 0
        },
        { status: 400 }
      );
    }

    const paperRunSeconds = parseBoundedInt(body.paperRunSeconds, {
      field: 'paperRunSeconds',
      min: 10,
      max: 3600
    });
    if (!paperRunSeconds.ok) {
      return NextResponse.json(
        {
          status: 'error',
          exit_code: -1,
          stdout: '',
          stderr: paperRunSeconds.error,
          duration_ms: 0
        },
        { status: 400 }
      );
    }

    // Build powershell arguments from body params
    const psArgs: string[] = [
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      path.join(PROJECT_ROOT, 'run_algo.ps1')
    ];

    psArgs.push('-ConfigPath', configPath.value);
    psArgs.push('-ExecutionProfile', executionProfile);
    psArgs.push('-MaxSplits', String(maxSplits.value));
    psArgs.push('-PaperRunSeconds', String(paperRunSeconds.value));
    if (parseRunFlag(body.skipTraining)) psArgs.push('-SkipTraining');
    if (parseRunFlag(body.skipWalkforward)) psArgs.push('-SkipWalkforward');
    if (parseRunFlag(body.skipPaperSession)) psArgs.push('-SkipPaperSession');

    const startTime = Date.now();

    const result = await new Promise<RunResult>((resolve) => {
      let stdout = '';
      let stderr = '';

      const proc = spawn('powershell', psArgs, {
        cwd: PROJECT_ROOT,
        windowsHide: true
      });

      proc.stdout.on('data', (chunk: Buffer) => {
        stdout += chunk.toString();
      });

      proc.stderr.on('data', (chunk: Buffer) => {
        stderr += chunk.toString();
      });

      proc.on('close', (exitCode) => {
        const duration_ms = Date.now() - startTime;
        const status = exitCode === 0 ? 'success' : 'error';

        // Write log to latest_run
        try {
          fs.mkdirSync(LATEST_RUN_DIR, { recursive: true });
          fs.writeFileSync(
            path.join(LATEST_RUN_DIR, 'run.log'),
            `=== Run started ===\n${new Date().toISOString()}\n\n` +
              `=== STDOUT ===\n${stdout}\n\n` +
              `=== STDERR ===\n${stderr}\n\n` +
              `=== Exit code: ${exitCode} ===\n`
          );
        } catch {
          // Non-fatal: log write failure
        }

        resolve({ status, exit_code: exitCode ?? -1, stdout, stderr, duration_ms });
      });

      proc.on('error', (err) => {
        resolve({
          status: 'error',
          exit_code: -1,
          stdout: '',
          stderr: err.message,
          duration_ms: Date.now() - startTime
        });
      });
    });

    return NextResponse.json(result, {
      status: result.status === 'success' ? 200 : 500
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { status: 'error', exit_code: -1, stdout: '', stderr: message, duration_ms: 0 },
      { status: 500 }
    );
  }
}
