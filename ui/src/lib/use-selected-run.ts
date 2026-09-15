'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';

export const RUN_ID_STORAGE_KEY = 'fxhe.selectedRunId';

function readStoredRunId(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  const value = window.localStorage.getItem(RUN_ID_STORAGE_KEY)?.trim();
  return value ? value : null;
}

export function persistSelectedRunId(runId: string | null): void {
  if (typeof window === 'undefined') {
    return;
  }
  if (runId && runId.trim()) {
    window.localStorage.setItem(RUN_ID_STORAGE_KEY, runId.trim());
  } else {
    window.localStorage.removeItem(RUN_ID_STORAGE_KEY);
  }
}

export function useSelectedRunId(): string | null {
  const searchParams = useSearchParams();
  const queryRunId = searchParams.get('runId')?.trim() || null;
  const [selectedRunId, setSelectedRunId] = useState<string | null>(queryRunId);

  useEffect(() => {
    if (queryRunId) {
      persistSelectedRunId(queryRunId);
      setSelectedRunId(queryRunId);
      return;
    }
    setSelectedRunId(readStoredRunId());
  }, [queryRunId]);

  return selectedRunId;
}
