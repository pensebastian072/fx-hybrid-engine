import { NextResponse } from 'next/server';
import type { RunsResponse } from '@/lib/fx-types';
import { listPaperRuns } from '@/lib/server-artifacts';

export async function GET() {
  const response: RunsResponse = {
    runs: listPaperRuns()
  };
  return NextResponse.json(response);
}
