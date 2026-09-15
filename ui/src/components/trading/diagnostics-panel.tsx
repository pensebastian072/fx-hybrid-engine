'use client';

import { useState } from 'react';
import type { DiagnosticEvent, RunManifest } from '@/lib/fx-types';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  IconAlertTriangle,
  IconChevronDown,
  IconChevronRight,
  IconRefresh,
  IconFile
} from '@tabler/icons-react';
import { format } from 'date-fns';

const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  data: { label: 'Data Issues', color: 'text-yellow-400' },
  execution: { label: 'Execution Issues', color: 'text-orange-400' },
  risk: { label: 'Risk Guardrails', color: 'text-red-400' },
  orders: { label: 'Order Placement', color: 'text-purple-400' },
  exit: { label: 'Exit Logic', color: 'text-blue-400' }
};

function groupByCategory(events: DiagnosticEvent[]) {
  const groups: Record<string, DiagnosticEvent[]> = {};
  for (const ev of events) {
    if (!groups[ev.category]) groups[ev.category] = [];
    groups[ev.category].push(ev);
  }
  return groups;
}

interface DiagnosticsPanelProps {
  manifest: RunManifest;
  logAvailable: boolean;
  onReplay?: () => void;
}

export function DiagnosticsPanel({
  manifest,
  logAvailable,
  onReplay
}: DiagnosticsPanelProps) {
  const [open, setOpen] = useState(false);

  const allEvents: DiagnosticEvent[] = [
    ...manifest.errors,
    ...manifest.warnings
  ].sort((a, b) => a.timestamp.localeCompare(b.timestamp));

  const hasIssues = allEvents.length > 0;

  const errorGroups = groupByCategory(manifest.errors);
  const warnGroups = groupByCategory(manifest.warnings);
  const allCategories = new Set([
    ...Object.keys(errorGroups),
    ...Object.keys(warnGroups)
  ]);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className='flex items-center justify-between'>
        <CollapsibleTrigger asChild>
          <button className='flex items-center gap-2 text-sm font-medium hover:text-foreground'>
            {open ? (
              <IconChevronDown className='h-4 w-4' />
            ) : (
              <IconChevronRight className='h-4 w-4' />
            )}
            <IconAlertTriangle
              className={`h-4 w-4 ${hasIssues ? 'text-yellow-400' : 'text-green-400'}`}
            />
            Why It Failed / Run Diagnostics
            <Badge variant={hasIssues ? 'destructive' : 'secondary'} className='text-xs'>
              {manifest.errors.length} errors · {manifest.warnings.length} warnings
            </Badge>
          </button>
        </CollapsibleTrigger>
        <div className='flex gap-2'>
          {onReplay && (
            <Button
              size='sm'
              variant='outline'
              onClick={onReplay}
              className='h-7 text-xs'
            >
              <IconRefresh className='mr-1 h-3 w-3' />
              Replay
            </Button>
          )}
          {logAvailable && (
            <Button
              size='sm'
              variant='ghost'
              className='h-7 text-xs'
              asChild
            >
              <a href='/api/log' target='_blank' rel='noreferrer'>
                <IconFile className='mr-1 h-3 w-3' />
                View Log
              </a>
            </Button>
          )}
        </div>
      </div>

      <CollapsibleContent className='mt-3 space-y-3'>
        {!hasIssues && (
          <p className='text-muted-foreground text-sm'>
            ✅ No errors or warnings. Run completed cleanly.
          </p>
        )}

        {Array.from(allCategories).map((cat) => {
          const errors = errorGroups[cat] ?? [];
          const warns = warnGroups[cat] ?? [];
          const meta =
            CATEGORY_LABELS[cat] ??
            { label: cat, color: 'text-foreground' };

          return (
            <div key={cat} className='space-y-1'>
              <p className={`text-xs font-semibold uppercase ${meta.color}`}>
                {meta.label}
              </p>
              {errors.map((e, i) => (
                <div
                  key={`err-${i}`}
                  className='bg-destructive/10 border-destructive/30 rounded border px-3 py-2 text-xs'
                >
                  <span className='text-destructive font-medium'>ERROR</span>{' '}
                  {e.message}
                  <span className='text-muted-foreground ml-2'>
                    {format(new Date(e.timestamp), 'HH:mm:ss')}
                  </span>
                </div>
              ))}
              {warns.map((w, i) => (
                <div
                  key={`warn-${i}`}
                  className='rounded border border-yellow-800/30 bg-yellow-900/10 px-3 py-2 text-xs'
                >
                  <span className='font-medium text-yellow-400'>WARN</span>{' '}
                  {w.message}
                  <span className='text-muted-foreground ml-2'>
                    {format(new Date(w.timestamp), 'HH:mm:ss')}
                  </span>
                </div>
              ))}
            </div>
          );
        })}

        {manifest.notes.length > 0 && (
          <div className='space-y-1'>
            <p className='text-muted-foreground text-xs font-semibold uppercase'>
              Notes
            </p>
            {manifest.notes.map((note, i) => (
              <p key={i} className='text-muted-foreground text-xs'>
                {note}
              </p>
            ))}
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
