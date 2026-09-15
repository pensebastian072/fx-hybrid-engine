import type { Trade } from '@/lib/fx-types';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

interface ActiveTradeCardProps {
  trades: Trade[];
}

function formatPips(pnl: number): string {
  return (pnl >= 0 ? '+' : '') + (pnl * 10000).toFixed(1) + ' pips';
}

export function ActiveTradeCard({ trades }: ActiveTradeCardProps) {
  const open = trades.filter((t) => t.exit_time === null);
  const latest = open[open.length - 1] ?? null;
  const latestClosed =
    trades
      .filter((t) => t.exit_time !== null)
      .sort((a, b) =>
        (b.exit_time ?? b.time).localeCompare(a.exit_time ?? a.time)
      )[0] ?? null;

  if (!latest) {
    if (!latestClosed) {
      return (
        <Card>
          <CardHeader>
            <CardTitle className='text-sm font-medium'>Trade Snapshot</CardTitle>
            <CardDescription>No trades available</CardDescription>
          </CardHeader>
          <CardContent>
            <p className='text-muted-foreground text-xs'>
              Run the algo to generate signals and trade history.
            </p>
          </CardContent>
        </Card>
      );
    }

    const closedProfit = latestClosed.pnl >= 0;
    return (
      <Card>
        <CardHeader className='pb-2'>
          <div className='flex items-center justify-between'>
            <CardTitle className='text-sm font-medium'>Latest Closed Trade</CardTitle>
            <Badge variant={closedProfit ? 'default' : 'destructive'}>
              {latestClosed.side.toUpperCase()}
            </Badge>
          </div>
          <CardDescription className='flex items-center gap-2'>
            <span className='text-base font-semibold text-foreground'>
              {latestClosed.symbol}
            </span>
            <span className='text-xs'>via {latestClosed.engine_source}</span>
          </CardDescription>
        </CardHeader>
        <CardContent className='space-y-2 text-sm'>
          <div className='grid grid-cols-2 gap-x-4 gap-y-1'>
            <div className='text-muted-foreground'>Entry</div>
            <div className='font-mono'>{latestClosed.entry.toFixed(5)}</div>
            <div className='text-muted-foreground'>Exit</div>
            <div className='font-mono'>{latestClosed.exit?.toFixed(5) ?? '—'}</div>
            <div className='text-muted-foreground'>Close Reason</div>
            <div className='truncate'>{latestClosed.close_reason ?? '—'}</div>
            <div className='text-muted-foreground'>Regime</div>
            <div>
              <Badge variant='outline' className='text-xs'>
                {latestClosed.regime_at_entry}
              </Badge>
            </div>
          </div>
          <div
            className={`text-right text-base font-semibold ${
              closedProfit ? 'text-green-400' : 'text-red-400'
            }`}
          >
            {formatPips(latestClosed.pnl)}
          </div>
        </CardContent>
      </Card>
    );
  }

  const isProfit = latest.pnl >= 0;

  return (
    <Card>
      <CardHeader className='pb-2'>
        <div className='flex items-center justify-between'>
          <CardTitle className='text-sm font-medium'>Active Trade</CardTitle>
          <Badge variant={isProfit ? 'default' : 'destructive'}>
            {latest.side.toUpperCase()}
          </Badge>
        </div>
        <CardDescription className='flex items-center gap-2'>
          <span className='font-semibold text-base text-foreground'>{latest.symbol}</span>
          <span className='text-xs'>via {latest.engine_source}</span>
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-2 text-sm'>
        <div className='grid grid-cols-2 gap-x-4 gap-y-1'>
          <div className='text-muted-foreground'>Entry</div>
          <div className='font-mono'>{latest.entry.toFixed(5)}</div>
          <div className='text-muted-foreground'>Stop Loss</div>
          <div className='font-mono text-red-400'>{latest.stop.toFixed(5)}</div>
          <div className='text-muted-foreground'>Take Profit</div>
          <div className='font-mono text-green-400'>{latest.take_profit.toFixed(5)}</div>
          <div className='text-muted-foreground'>Size</div>
          <div className='font-mono'>{latest.size.toFixed(2)} lot</div>
          <div className='text-muted-foreground'>Regime</div>
          <div>
            <Badge variant='outline' className='text-xs'>
              {latest.regime_at_entry}
            </Badge>
          </div>
        </div>
        <div
          className={`text-right text-base font-semibold ${
            isProfit ? 'text-green-400' : 'text-red-400'
          }`}
        >
          {formatPips(latest.pnl)}
        </div>
      </CardContent>
    </Card>
  );
}
