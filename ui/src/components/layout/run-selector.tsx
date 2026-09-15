'use client';

import { useCallback, useEffect, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { fetchRuns } from '@/lib/artifacts';
import type { RunCatalogEntry } from '@/lib/fx-types';
import {
  persistSelectedRunId,
  RUN_ID_STORAGE_KEY,
  useSelectedRunId
} from '@/lib/use-selected-run';

const LATEST_VALUE = '__latest__';

function optionLabel(run: RunCatalogEntry): string {
  const startedAt = run.started_at ? run.started_at.slice(5, 16).replace('T', ' ') : 'unknown';
  const context = run.artifact_context === 'paper_strategy' ? 'strategy' : 'scaffold';
  return `${run.run_id} · ${context} · ${startedAt}`;
}

export function RunSelector() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selectedRunId = useSelectedRunId();
  const [runs, setRuns] = useState<RunCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchRuns();
      setRuns(response.runs);
    } catch {
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const currentValue = selectedRunId ?? LATEST_VALUE;
  const selectedRun = runs.find((run) => run.run_id === selectedRunId) ?? null;

  const onValueChange = useCallback(
    (value: string) => {
      const nextRunId = value === LATEST_VALUE ? null : value;
      persistSelectedRunId(nextRunId);
      const params = new URLSearchParams(searchParams.toString());
      if (nextRunId) {
        params.set('runId', nextRunId);
      } else {
        params.delete('runId');
        if (typeof window !== 'undefined') {
          window.localStorage.removeItem(RUN_ID_STORAGE_KEY);
        }
      }
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  return (
    <div className='hidden items-center gap-2 xl:flex'>
      <Badge variant={selectedRun ? 'secondary' : 'outline'} className='text-[10px] uppercase'>
        {selectedRun ? 'Historical Run' : 'Latest Projection'}
      </Badge>
      <Select value={currentValue} onValueChange={onValueChange} disabled={loading}>
        <SelectTrigger className='h-9 w-[280px] text-xs'>
          <SelectValue placeholder='Select run scope' />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={LATEST_VALUE}>Latest normalized artifacts</SelectItem>
          {runs.map((run) => (
            <SelectItem key={run.run_id} value={run.run_id}>
              {optionLabel(run)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
