'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { PriceChart } from '@/components/charts/price-chart';
import { EquityChart } from '@/components/charts/equity-chart';
import { ActiveTradeCard } from '@/components/trading/active-trade-card';
import { TradeHistoryTable } from '@/components/trading/trade-history-table';
import { DiagnosticsPanel } from '@/components/trading/diagnostics-panel';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DashboardEmptyState } from '@/components/dashboard/empty-state';
import { ProvenanceBadge } from '@/components/dashboard/provenance-badge';
import {
  fetchAlgoState,
  fetchRegimeData,
  fetchWalkforwardData
} from '@/lib/artifacts';
import type {
  AlgoState,
  OpsEvent,
  RegimeResponse,
  WalkforwardResponse
} from '@/lib/fx-types';
import { IconAlertTriangle, IconRefresh } from '@tabler/icons-react';
import { format } from 'date-fns';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';

const REGIME_BADGE_VARIANT: Record<string, 'default' | 'secondary' | 'destructive'> = {
  TREND: 'default',
  CHOP: 'secondary',
  RISK_OFF: 'destructive'
};

const EVENT_COLOR: Record<string, string> = {
  regime_transition: 'text-blue-400',
  breaker_trigger: 'text-red-400',
  pair_disable: 'text-orange-400',
  pair_enable: 'text-green-400',
  signal_reject: 'text-yellow-400',
  stale_data: 'text-orange-400',
  deploy_change: 'text-sky-400',
  close_only_engage: 'text-red-500',
  close_only_disengage: 'text-green-500',
  risk_event: 'text-red-400'
};

interface AlgoPageData {
  state: AlgoState;
  walkforward: WalkforwardResponse;
  regime: RegimeResponse;
}

function formatUsd(value: number | undefined | null) {
  if (value === undefined || value === null) {
    return '—';
  }
  return `${value >= 0 ? '+' : '-'}$${Math.abs(value).toFixed(0)}`;
}

function formatPercent(value: number | undefined | null) {
  if (value === undefined || value === null) {
    return '—';
  }
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
}

export default function AlgoDashboardPage() {
  const [data, setData] = useState<AlgoPageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [state, walkforward, regime] = await Promise.all([
        fetchAlgoState(),
        fetchWalkforwardData(),
        fetchRegimeData()
      ]);
      setData({ state, walkforward, regime });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const drawdownData = useMemo(() => {
    const equityCurve = data?.state.equity_curve ?? [];
    let peak = -Infinity;
    return equityCurve.map((point) => {
      if (point.equity > peak) {
        peak = point.equity;
      }
      const drawdown = peak > 0 ? ((point.equity - peak) / peak) * 100 : 0;
      return {
        date: point.timestamp.slice(5, 10),
        drawdown: +drawdown.toFixed(2)
      };
    });
  }, [data]);

  if (loading) {
    return (
      <PageContainer>
        <div className='flex h-64 items-center justify-center'>
          <p className='text-muted-foreground text-sm'>Loading artifacts…</p>
        </div>
      </PageContainer>
    );
  }

  if (error || !data) {
    return (
      <PageContainer>
        <DashboardEmptyState
          title='Algo dashboard unavailable'
          description={error ?? 'No state loaded.'}
          action={
            <Button variant='outline' onClick={load}>
              Retry
            </Button>
          }
        />
      </PageContainer>
    );
  }

  const { state, walkforward, regime } = data;
  const { manifest, trades, candles, equity_curve, events, provenance, log_available } = state;
  const regimeProbabilities = manifest.regime_probabilities ?? {};
  const hasSymbolSpecificCandles = candles.some((candle) => Boolean(candle.symbol));
  const hasRunScopedCandles =
    provenance.files.candles === 'latest_run' || provenance.files.candles === 'run_history';
  const isReferencePrice = !hasSymbolSpecificCandles || !hasRunScopedCandles;
  const showingHistoricalWalkforward = manifest.artifact_context === 'historical_walkforward';
  const showingPaperScaffold = manifest.artifact_context === 'paper_scaffold';
  const simulatedPaperData = manifest.artifact_context === 'paper_strategy' && manifest.simulated_market_data === true;
  const localPaperRouting = manifest.broker_order_routing === 'local_paper_only';
  const allocationData = regime.engine_allocations.map((allocation) => ({
    date: allocation.timestamp.slice(0, 10),
    Pairs: +(allocation.pairs_alloc * 100).toFixed(1),
    Trend: +(allocation.trend_alloc * 100).toFixed(1)
  }));
  const dataHealthRows = [
    ['Manifest', provenance.files.manifest],
    ['Trades', provenance.files.trades],
    ['Candles', provenance.files.candles],
    ['Events', provenance.files.events],
    ['Promotion', walkforward.provenance.files.promotion_decision],
    ['Allocations', regime.provenance.files.engine_allocations]
  ] as const;

  return (
    <PageContainer>
      <div className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div className='space-y-2'>
            <div className='flex flex-wrap items-center gap-2'>
              <h2 className='text-2xl font-bold tracking-tight'>{manifest.active_symbol}</h2>
              <Badge variant={REGIME_BADGE_VARIANT[manifest.regime] ?? 'secondary'}>
                {manifest.regime}
              </Badge>
              <Badge variant='outline'>{manifest.status}</Badge>
              <ProvenanceBadge source={provenance.overall} />
            </div>
            <p className='text-muted-foreground text-sm'>
              Last session update: {format(new Date(manifest.ended_at), 'MMM d, yyyy HH:mm')} UTC
            </p>
          </div>
          <Button size='sm' variant='outline' onClick={load}>
            <IconRefresh className='mr-1 h-3 w-3' />
            Refresh
          </Button>
        </div>

        {showingHistoricalWalkforward && (
          <Card className='border-yellow-500/30 bg-yellow-500/5'>
            <CardContent className='flex items-center gap-2 pt-6 text-sm'>
              <IconAlertTriangle className='h-4 w-4 text-yellow-500' />
              The current trades view is showing the latest walk-forward artifacts, not an active paper session.
            </CardContent>
          </Card>
        )}

        {showingPaperScaffold && (
          <Card className='border-yellow-500/30 bg-yellow-500/5'>
            <CardContent className='flex items-center gap-2 pt-6 text-sm'>
              <IconAlertTriangle className='h-4 w-4 text-yellow-500' />
              A paper session was initialized, but no strategy-cycle artifacts have been emitted yet.
            </CardContent>
          </Card>
        )}

        {simulatedPaperData && (
          <Card className='border-blue-500/30 bg-blue-500/5'>
            <CardContent className='flex items-center gap-2 pt-6 text-sm'>
              <IconAlertTriangle className='h-4 w-4 text-blue-400' />
              Current paper artifacts use `lean_history` synthetic market data, so timestamps are current but prices are simulated.
            </CardContent>
          </Card>
        )}

        {!showingHistoricalWalkforward && localPaperRouting && (
          <Card className='border-blue-500/30 bg-blue-500/5'>
            <CardContent className='flex items-center gap-2 pt-6 text-sm'>
              <IconAlertTriangle className='h-4 w-4 text-blue-400' />
              Orders are still routed as local paper fills only; no Tastytrade order has been submitted from this view yet.
            </CardContent>
          </Card>
        )}

        <div className='grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6'>
          {[
            {
              label: 'Daily PnL',
              value: formatUsd(manifest.daily_pnl),
              subvalue: formatPercent(manifest.daily_pnl_pct),
              positive: (manifest.daily_pnl ?? 0) >= 0
            },
            {
              label: 'Weekly PnL',
              value: formatUsd(manifest.weekly_pnl),
              subvalue: formatPercent(manifest.weekly_pnl_pct),
              positive: (manifest.weekly_pnl ?? 0) >= 0
            },
            {
              label: 'Total Return',
              value: formatPercent(manifest.metrics?.total_return),
              subvalue: `${manifest.metrics?.num_trades ?? 0} trades`,
              positive: (manifest.metrics?.total_return ?? 0) >= 0
            },
            {
              label: 'Sharpe',
              value: manifest.metrics?.sharpe_ratio?.toFixed(2) ?? '—',
              subvalue: `Win rate ${formatPercent(manifest.metrics?.win_rate)}`,
              positive: (manifest.metrics?.sharpe_ratio ?? 0) >= 0
            },
            {
              label: 'Max Drawdown',
              value: manifest.metrics ? `${(manifest.metrics.max_drawdown * 100).toFixed(2)}%` : '—',
              subvalue: walkforward.proof_checks?.pass ? 'Proof checks passing' : 'Proof checks failing',
              positive: false
            },
            {
              label: 'Gross Exposure',
              value: manifest.gross_exposure_pct !== undefined ? `${(manifest.gross_exposure_pct * 100).toFixed(0)}%` : '—',
              subvalue: manifest.close_only === true ? 'Close-only ON' : 'Close-only OFF',
              positive: manifest.close_only !== true
            }
          ].map((item) => (
            <Card key={item.label}>
              <CardHeader className='pb-1 pt-3'>
                <CardDescription className='text-xs'>{item.label}</CardDescription>
                <CardTitle className={`text-lg font-semibold tabular-nums ${item.label.includes('Drawdown') ? 'text-orange-400' : item.positive ? 'text-green-500' : 'text-red-500'}`}>
                  {item.value}
                </CardTitle>
                <p className='text-muted-foreground text-xs'>{item.subvalue}</p>
              </CardHeader>
            </Card>
          ))}
        </div>

        <div className='grid grid-cols-1 gap-4 xl:grid-cols-3'>
          <Card className='xl:col-span-2'>
            <CardHeader className='pb-2'>
              <CardTitle className='text-sm font-medium'>Equity Curve</CardTitle>
              <CardDescription>Main operator view for current strategy equity.</CardDescription>
            </CardHeader>
            <CardContent>
              {equity_curve.length > 0 ? (
                <EquityChart data={equity_curve} />
              ) : (
                <DashboardEmptyState
                  title='Equity curve unavailable'
                  description='No equity_curve.json data is available for the current session artifact set.'
                />
              )}
            </CardContent>
          </Card>

          <div className='flex flex-col gap-4'>
            <Card>
              <CardHeader className='pb-2'>
                <CardTitle className='text-sm font-medium'>Promotion & Ladder</CardTitle>
              </CardHeader>
              <CardContent className='space-y-3 text-sm'>
                {walkforward.promotion_decision ? (
                  <>
                    <div className='flex items-center justify-between'>
                      <span className='text-muted-foreground'>Decision</span>
                      <Badge variant={walkforward.promotion_decision.pass ? 'default' : 'destructive'}>
                        {walkforward.promotion_decision.pass ? 'GO' : 'NO-GO'}
                      </Badge>
                    </div>
                    <div className='flex items-center justify-between'>
                      <span className='text-muted-foreground'>Stage</span>
                      <span className='font-mono'>{walkforward.promotion_decision.ladder.current_stage}</span>
                    </div>
                    <div className='flex items-center justify-between'>
                      <span className='text-muted-foreground'>Action</span>
                      <span className='font-medium capitalize'>
                        {walkforward.promotion_decision.ladder.action}
                      </span>
                    </div>
                    {walkforward.promotion_decision.failed_reasons.length > 0 && (
                      <div className='flex flex-wrap gap-1'>
                        {walkforward.promotion_decision.failed_reasons.map((reason) => (
                          <Badge key={reason} variant='destructive' className='text-xs'>
                            {reason.replace(/_/g, ' ')}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <DashboardEmptyState
                    title='Promotion data unavailable'
                    description='No promotion_decision artifact is available for the current session artifact set.'
                  />
                )}
              </CardContent>
            </Card>

            <ActiveTradeCard trades={trades} />

            <Card>
              <CardHeader className='pb-2'>
                <CardTitle className='text-sm font-medium'>Session Health & Data Sources</CardTitle>
              </CardHeader>
              <CardContent className='space-y-3'>
                <div className='grid grid-cols-2 gap-2 text-xs'>
                  <div className='rounded border p-2'>
                    <p className='text-muted-foreground'>Close-only</p>
                    <p className='font-semibold'>{manifest.close_only ? 'ON' : 'OFF'}</p>
                  </div>
                  <div className='rounded border p-2'>
                    <p className='text-muted-foreground'>Session Log</p>
                    <p className='font-semibold'>{log_available ? 'Available' : 'Missing'}</p>
                  </div>
                </div>
                <div className='space-y-2'>
                  {dataHealthRows.map(([label, source]) => (
                    <div key={label} className='flex items-center justify-between gap-2 text-xs'>
                      <span className='text-muted-foreground'>{label}</span>
                      <ProvenanceBadge source={source} />
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        <div className='grid grid-cols-1 gap-4 xl:grid-cols-2'>
          <Card>
            <CardHeader className='pb-2'>
              <CardTitle className='text-sm font-medium'>Drawdown</CardTitle>
              <CardDescription>Rolling drawdown from peak equity.</CardDescription>
            </CardHeader>
            <CardContent>
              {drawdownData.length > 0 ? (
                <ResponsiveContainer width='100%' height={140}>
                  <AreaChart data={drawdownData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                    <XAxis dataKey='date' tick={{ fontSize: 9 }} tickLine={false} />
                    <YAxis tick={{ fontSize: 9 }} unit='%' />
                    <Tooltip formatter={(value: number) => `${value}%`} />
                    <Area type='monotone' dataKey='drawdown' fill='#ef4444' stroke='#ef4444' fillOpacity={0.3} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <DashboardEmptyState
                  title='No drawdown history available'
                  description='Drawdown requires an equity curve with more than one point.'
                />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className='pb-2'>
              <div className='flex items-center justify-between gap-2'>
                <div>
                  <CardTitle className='text-sm font-medium'>Engine Allocation</CardTitle>
                  <CardDescription>Pairs vs trend capital allocation over time.</CardDescription>
                </div>
                <ProvenanceBadge source={regime.provenance.files.engine_allocations} />
              </div>
            </CardHeader>
            <CardContent>
              {allocationData.length > 0 ? (
                <ResponsiveContainer width='100%' height={140}>
                  <AreaChart data={allocationData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                    <XAxis dataKey='date' tick={{ fontSize: 9 }} tickLine={false} />
                    <YAxis tick={{ fontSize: 9 }} unit='%' />
                    <Tooltip formatter={(value: number) => `${value}%`} />
                    <Area type='monotone' dataKey='Pairs' fill='#8b5cf6' stroke='#8b5cf6' fillOpacity={0.6} />
                    <Area type='monotone' dataKey='Trend' fill='#06b6d4' stroke='#06b6d4' fillOpacity={0.6} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <DashboardEmptyState
                  title='Allocation history unavailable'
                  description='No engine allocation history was emitted for the current session artifact set.'
                />
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className='pb-2'>
            <div className='flex items-center justify-between gap-2'>
              <div>
                <CardTitle className='text-sm font-medium'>Reference Price</CardTitle>
                <CardDescription>
                  {isReferencePrice
                    ? 'Shown as a reference series only. The current artifact set does not provide symbol-specific live candles.'
                    : 'Symbol-specific candles for the active instrument.'}
                </CardDescription>
              </div>
              <ProvenanceBadge source={provenance.files.candles} />
            </div>
          </CardHeader>
          <CardContent>
            {candles.length > 0 ? (
              <PriceChart candles={candles} symbol={manifest.active_symbol} />
            ) : (
              <DashboardEmptyState
                title='Reference price unavailable'
                description='No candle series was emitted for the current session artifact set, and no fallback candles are available.'
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='pb-2'>
            <div className='flex items-center justify-between gap-2'>
              <div>
                <CardTitle className='text-sm font-medium'>Events Feed</CardTitle>
                <CardDescription>
                  Regime changes, breaker triggers, pair state updates, and data alerts.
                </CardDescription>
              </div>
              <ProvenanceBadge source={provenance.files.events} />
            </div>
          </CardHeader>
          <CardContent>
            {events.length > 0 ? (
              <div className='space-y-2'>
                {events.slice(0, 50).map((event: OpsEvent, index: number) => (
                  <div key={`${event.timestamp}-${index}`} className='flex items-start gap-3 border-b pb-2 last:border-0'>
                    <span className='text-muted-foreground mt-0.5 shrink-0 text-xs'>
                      {format(new Date(event.timestamp), 'MM-dd HH:mm')}
                    </span>
                    <span className={`shrink-0 text-xs font-medium ${EVENT_COLOR[event.event_type] ?? 'text-muted-foreground'}`}>
                      {event.event_type.replace(/_/g, ' ')}
                    </span>
                    <span className='text-muted-foreground text-xs'>{event.message}</span>
                    {event.symbols && event.symbols.length > 0 && (
                      <div className='ml-auto flex shrink-0 gap-1'>
                        {event.symbols.map((symbol, symbolIndex) => (
                          <Badge key={`${symbol}-${symbolIndex}`} variant='outline' className='text-xs'>
                            {symbol}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <DashboardEmptyState
                title='No events available'
                description='The current session artifact set did not emit an events artifact, and no fallback events are available.'
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Trade History</CardTitle>
            <CardDescription>
              {trades.filter((trade) => trade.exit_time !== null).length} closed trades
            </CardDescription>
          </CardHeader>
          <CardContent>
            <TradeHistoryTable trades={trades} />
          </CardContent>
        </Card>

        <Card>
          <CardContent className='pt-4'>
            <DiagnosticsPanel
              manifest={manifest}
              logAvailable={log_available}
              onReplay={load}
            />
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
