import { NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';

const PROJECT_ROOT = path.resolve(process.cwd(), '..');
const LOG_PATH = path.join(PROJECT_ROOT, 'artifacts', 'latest_run', 'run.log');

export async function GET() {
  try {
    if (!fs.existsSync(LOG_PATH)) {
      return NextResponse.json({ content: null, exists: false });
    }
    const content = fs.readFileSync(LOG_PATH, 'utf-8');
    return NextResponse.json({ content, exists: true });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
