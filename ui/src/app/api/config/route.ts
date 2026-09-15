import { NextRequest, NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';

const PROJECT_ROOT = path.resolve(process.cwd(), '..');
const CONFIG_DIR = path.join(PROJECT_ROOT, 'config');
const MAX_CONFIG_BYTES = 256 * 1024;

const ALLOWED_FILES: Record<string, string> = {
  default: 'default.yaml',
  pairs_policy: 'pairs_policy.yaml',
  ladder: 'ladder.yaml'
};

function resolveFile(name: string): { filePath: string; filename: string } | null {
  const filename = ALLOWED_FILES[name];
  if (!filename) {
    return null;
  }
  return {
    filePath: path.join(CONFIG_DIR, filename),
    filename
  };
}

export async function GET(req: NextRequest) {
  const file = req.nextUrl.searchParams.get('file') ?? '';
  const resolved = resolveFile(file);

  if (!resolved) {
    return NextResponse.json(
      { error: `Unknown config file: ${file}` },
      { status: 400 }
    );
  }

  if (!fs.existsSync(resolved.filePath)) {
    return NextResponse.json(
      { error: `Config file not found on disk: ${resolved.filename}` },
      { status: 404 }
    );
  }

  const content = fs.readFileSync(resolved.filePath, 'utf-8');
  return new NextResponse(content, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' }
  });
}

export async function POST(req: NextRequest) {
  const file = req.nextUrl.searchParams.get('file') ?? '';
  const resolved = resolveFile(file);

  if (!resolved) {
    return NextResponse.json(
      { error: `Unknown config file: ${file}` },
      { status: 400 }
    );
  }

  if (!fs.existsSync(resolved.filePath)) {
    return NextResponse.json(
      { error: `Config file not found on disk: ${resolved.filename}` },
      { status: 404 }
    );
  }

  const body = await req.text();
  if (!body.trim()) {
    return NextResponse.json({ error: 'Content is empty' }, { status: 400 });
  }
  if (body.includes('\0')) {
    return NextResponse.json({ error: 'Invalid content' }, { status: 400 });
  }
  const contentSize = Buffer.byteLength(body, 'utf-8');
  if (contentSize > MAX_CONFIG_BYTES) {
    return NextResponse.json(
      { error: `Content too large (${contentSize} bytes). Max allowed is ${MAX_CONFIG_BYTES} bytes.` },
      { status: 400 }
    );
  }

  const normalizedBody = body.replace(/\r\n/g, '\n');

  try {
    const backupPath = `${resolved.filePath}.bak-${Date.now()}`;
    fs.copyFileSync(resolved.filePath, backupPath);
    fs.writeFileSync(resolved.filePath, normalizedBody, 'utf-8');
    return NextResponse.json({ ok: true, file: resolved.filename, backup: path.basename(backupPath) });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
