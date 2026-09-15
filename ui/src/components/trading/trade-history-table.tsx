'use client';

import { useState, useMemo } from 'react';
import type { Trade } from '@/lib/fx-types';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { IconChevronUp, IconChevronDown } from '@tabler/icons-react';
import { format } from 'date-fns';

type SortKey = 'time' | 'symbol' | 'side' | 'pnl_pct' | 'close_reason';
type SortDir = 'asc' | 'desc';

interface TradeHistoryTableProps {
  trades: Trade[];
}

function SortButton({
  label,
  field,
  sortKey,
  sortDir,
  onSort
}: {
  label: string;
  field: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
}) {
  const active = sortKey === field;
  return (
    <button
      className='flex items-center gap-1 hover:text-foreground'
      onClick={() => onSort(field)}
    >
      {label}
      {active ? (
        sortDir === 'asc' ? (
          <IconChevronUp className='h-3 w-3' />
        ) : (
          <IconChevronDown className='h-3 w-3' />
        )
      ) : (
        <IconChevronDown className='h-3 w-3 opacity-30' />
      )}
    </button>
  );
}

export function TradeHistoryTable({ trades }: TradeHistoryTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('time');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 10;

  const closed = trades.filter((t) => t.exit_time !== null);

  const sorted = useMemo(() => {
    return [...closed].sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'time') cmp = a.time.localeCompare(b.time);
      else if (sortKey === 'symbol') cmp = a.symbol.localeCompare(b.symbol);
      else if (sortKey === 'side') cmp = a.side.localeCompare(b.side);
      else if (sortKey === 'pnl_pct') cmp = a.pnl_pct - b.pnl_pct;
      else if (sortKey === 'close_reason')
        cmp = (a.close_reason ?? '').localeCompare(b.close_reason ?? '');
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [closed, sortKey, sortDir]);

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const paged = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function handleSort(key: SortKey) {
    if (key === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(key);
      setSortDir('desc');
    }
    setPage(0);
  }

  if (closed.length === 0) {
    return (
      <p className='text-muted-foreground py-4 text-sm'>
        No closed trades found.
      </p>
    );
  }

  return (
    <div className='space-y-2'>
      <Table>
        <TableHeader>
          <TableRow className='text-muted-foreground text-xs'>
            <TableHead>
              <SortButton
                label='Date'
                field='time'
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={handleSort}
              />
            </TableHead>
            <TableHead>
              <SortButton
                label='Symbol'
                field='symbol'
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={handleSort}
              />
            </TableHead>
            <TableHead>
              <SortButton
                label='Side'
                field='side'
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={handleSort}
              />
            </TableHead>
            <TableHead>Entry</TableHead>
            <TableHead>Exit</TableHead>
            <TableHead>
              <SortButton
                label='P&L %'
                field='pnl_pct'
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={handleSort}
              />
            </TableHead>
            <TableHead>
              <SortButton
                label='Reason'
                field='close_reason'
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={handleSort}
              />
            </TableHead>
            <TableHead>Regime</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {paged.map((t) => (
            <TableRow key={t.id} className='text-xs'>
              <TableCell className='font-mono'>
                {format(new Date(t.time), 'MMM d yy')}
              </TableCell>
              <TableCell className='font-semibold'>{t.symbol}</TableCell>
              <TableCell>
                <Badge
                  variant={t.side === 'long' ? 'default' : 'secondary'}
                  className='text-xs'
                >
                  {t.side.toUpperCase()}
                </Badge>
              </TableCell>
              <TableCell className='font-mono'>{t.entry.toFixed(5)}</TableCell>
              <TableCell className='font-mono'>
                {t.exit?.toFixed(5) ?? '-'}
              </TableCell>
              <TableCell
                className={`font-mono font-semibold ${
                  t.pnl_pct >= 0 ? 'text-green-400' : 'text-red-400'
                }`}
              >
                {t.pnl_pct >= 0 ? '+' : ''}
                {t.pnl_pct.toFixed(3)}%
              </TableCell>
              <TableCell className='text-muted-foreground max-w-[120px] truncate'>
                {t.close_reason ?? '-'}
              </TableCell>
              <TableCell>
                <Badge variant='outline' className='text-xs'>
                  {t.regime_at_entry}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {totalPages > 1 && (
        <div className='flex items-center justify-between text-xs'>
          <span className='text-muted-foreground'>
            Page {page + 1} of {totalPages} · {closed.length} trades
          </span>
          <div className='flex gap-2'>
            <Button
              size='sm'
              variant='outline'
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
            >
              Prev
            </Button>
            <Button
              size='sm'
              variant='outline'
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
