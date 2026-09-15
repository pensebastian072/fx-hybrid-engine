'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { DashboardEmptyState } from '@/components/dashboard/empty-state';
import { ProvenanceBadge } from '@/components/dashboard/provenance-badge';
import {
  fetchAlgoState,
  fetchAnalysisData,
  fetchRegimeData
} from '@/lib/artifacts';
import type {
  AlgoState,
  AnalysisResponse,
  RegimeResponse,
  Trade,
  TradeAnalyticsRow
} from '@/lib/fx-types';
import { IconRefresh, IconSearch } from '@tabler/icons-react';
import { differenceInMinutes, format } from 'date-fns';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';

const REGIME_BADGE: Record<string, 'default' | 'secondary' | 'destructive'> = {
  TREND: 'default',
  CHOP: 'secondary',
  RISK_OFF: 'destructive'
};

const ENGINE_BADGE: Record<string, 'default' | 'outline'> = {
  trend: 'default',
  pairs: 'outline'
};

function holdTime(entry: string, exit: string | null): string {
  if (!exit) {
    return 'open';
  }
  const minutes = differenceInMinutes(new Date(exit), new Date(entry));
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  return remaining > 0 ? `${hours}h ${remaining}m` : `${hours}h`;
}

interface TradePageData {
  state: AlgoState;
  regime: RegimeResponse;
  analysis: AnalysisResponse;
}

export default function TradesPage() {
  const [mounted, setMounted] = useState(false);
  const [data, setData] = useState<TradePageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Trade | null>(null);
  const [symbolFilter, setSymbolFilter] = useState('');
  const [engineFilter, setEngineFilter] = useState('all');
  const [regimeFilter, setRegimeFilter] = useState('all');
  const [outcomeFilter, setOutcomeFilter] = useState('all');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [state, regime, analysis] = await Promise.all([
        fetchAlgoState(),
        fetchRegimeData(),
        fetchAnalysisData()
      ]);
      setData({ state, regime, analysis });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const trades = data?.state.trades ?? [];
  const candles = data?.state.candles ?? [];
  const regimePosteriors = data?.regime.regime_posteriors ?? [];
  const analyticsRows = data?.analysis.analysis?.trade_analytics_rows ?? [];
  const hasSymbolSpecificCandles = candles.some((candle) => Boolean(candle.symbol));

  const filtered = useMemo(() => {
    return trades.filter((trade) => {
      if (symbolFilter && !trade.symbol.toLowerCase().includes(symbolFilter.toLowerCase())) {
        return false;
      }
      if (engineFilter !== 'all' && trade.engine_source !== engineFilter) {
        return false;
      }
      if (regimeFilter !== 'all' && trade.regime_at_entry !== regimeFilter) {
        return false;
      }
      if (outcomeFilter === 'win' && trade.pnl <= 0) {
        return false;
      }
      if (outcomeFilter === 'loss' && trade.pnl > 0) {
        return false;
      }
      if (outcomeFilter === 'open' && trade.exit_time !== null) {
        return false;
      }
      return true;
    });
  }, [trades, symbolFilter, engineFilter, regimeFilter, outcomeFilter]);

  const selectedSymbolCandles = useMemo(() => {
    if (!selected || !hasSymbolSpecificCandles) {
      return [];
    }
    return candles.filter((candle) => candle.symbol === selected.symbol).slice(-40);
  }, [candles, hasSymbolSpecificCandles, selected]);

  const drilldownChart = useMemo(() => {
    if (!selected || selectedSymbolCandles.length === 0) {
      return [];
    }
    return selectedSymbolCandles.map((candle) => ({
      time: candle.time.slice(5, 16),
      close: candle.close
    }));
  }, [selected, selectedSymbolCandles]);

  const drilldownRegime = useMemo(() => {
    if (!selected || regimePosteriors.length === 0) {
      return [];
    }
    const index = regimePosteriors.findIndex((posterior) => posterior.timestamp >= selected.time);
    const start = Math.max(0, index - 8);
    const end = Math.min(regimePosteriors.length, index + 8);
    return regimePosteriors.slice(start, end).map((posterior) => ({
      date: posterior.timestamp.slice(5, 16),
      TREND: +(posterior.TREND * 100).toFixed(1),
      CHOP: +(posterior.CHOP * 100).toFixed(1),
      RISK_OFF: +(posterior.RISK_OFF * 100).toFixed(1)
    }));
  }, [regimePosteriors, selected]);

  const selectedAnalytics = useMemo<TradeAnalyticsRow | null>(() => {
    if (!selected) {
      return null;
    }
    return analyticsRows.find((row) => row.trade_id === selected.id) ?? null;
  }, [analyticsRows, selected]);

  const candlesSource = data?.state.provenance.files.candles ?? 'missing';
  const analyticsSource = data?.analysis.provenance.files.analysis ?? 'missing';

  return (
    <PageContainer>
      <div className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>Trades</h2>
            <p className='text-muted-foreground text-sm'>
              Trade history with drilldowns for regime context and analytics.
            </p>
          </div>
          <div className='flex items-center gap-2'>
            {data && <ProvenanceBadge source={data.state.provenance.overall} />}
            <Button size='sm' variant='outline' onClick={load} disabled={loading}>
              <IconRefresh className='mr-1 h-3 w-3' />
              Refresh
            </Button>
          </div>
        </div>

        {error && (
          <DashboardEmptyState
            title='Trades data unavailable'
            description={error}
            action={
              <Button size='sm' variant='outline' onClick={load}>
                Retry
              </Button>
            }
          />
        )}

        {!error && (
          <>
            <div className='flex flex-wrap gap-2'>
              <div className='relative'>
                <IconSearch className='text-muted-foreground absolute top-2.5 left-2 h-3.5 w-3.5' />
                <Input
                  placeholder='Symbol…'
                  value={symbolFilter}
                  onChange={(event) => setSymbolFilter(event.target.value)}
                  className='h-8 w-32 pl-7 text-xs'
                />
              </div>
              {mounted ? (
                <>
                  <Select value={engineFilter} onValueChange={setEngineFilter}>
                    <SelectTrigger className='h-8 w-32 text-xs' aria-label='Filter by engine'>
                      <SelectValue placeholder='Engine' />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value='all'>All engines</SelectItem>
                      <SelectItem value='trend'>Trend</SelectItem>
                      <SelectItem value='pairs'>Pairs</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select value={regimeFilter} onValueChange={setRegimeFilter}>
                    <SelectTrigger className='h-8 w-32 text-xs' aria-label='Filter by regime'>
                      <SelectValue placeholder='Regime' />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value='all'>All regimes</SelectItem>
                      <SelectItem value='TREND'>TREND</SelectItem>
                      <SelectItem value='CHOP'>CHOP</SelectItem>
                      <SelectItem value='RISK_OFF'>RISK_OFF</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select value={outcomeFilter} onValueChange={setOutcomeFilter}>
                    <SelectTrigger className='h-8 w-32 text-xs' aria-label='Filter by outcome'>
                      <SelectValue placeholder='Outcome' />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value='all'>All outcomes</SelectItem>
                      <SelectItem value='win'>Win</SelectItem>
                      <SelectItem value='loss'>Loss</SelectItem>
                      <SelectItem value='open'>Open</SelectItem>
                    </SelectContent>
                  </Select>
                </>
              ) : (
                <>
                  <div className='bg-muted h-8 w-32 rounded-md' />
                  <div className='bg-muted h-8 w-32 rounded-md' />
                  <div className='bg-muted h-8 w-32 rounded-md' />
                </>
              )}
              {(symbolFilter || engineFilter !== 'all' || regimeFilter !== 'all' || outcomeFilter !== 'all') && (
                <Button
                  size='sm'
                  variant='ghost'
                  className='h-8 text-xs'
                  onClick={() => {
                    setSymbolFilter('');
                    setEngineFilter('all');
                    setRegimeFilter('all');
                    setOutcomeFilter('all');
                  }}
                >
                  Clear
                </Button>
              )}
            </div>

            <div className='grid grid-cols-1 gap-4 lg:grid-cols-5'>
              <Card className='lg:col-span-3'>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>Trade List</CardTitle>
                  <CardDescription>
                    {filtered.length} of {trades.length} trades match the current filters.
                  </CardDescription>
                </CardHeader>
                <CardContent className='p-0'>
                  <div className='overflow-auto'>
                    <table className='w-full text-sm'>
                      <thead>
                        <tr className='text-muted-foreground border-b text-xs'>
                          <th className='px-3 py-2 text-left font-medium'>Entry</th>
                          <th className='px-3 py-2 text-left font-medium'>Symbol</th>
                          <th className='px-3 py-2 text-left font-medium'>Engine</th>
                          <th className='px-3 py-2 text-left font-medium'>Regime</th>
                          <th className='px-3 py-2 text-right font-medium'>Size</th>
                          <th className='px-3 py-2 text-right font-medium'>Entry</th>
                          <th className='px-3 py-2 text-right font-medium'>Exit</th>
                          <th className='px-3 py-2 text-right font-medium'>PnL %</th>
                          <th className='px-3 py-2 text-right font-medium'>Hold</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filtered.map((trade) => (
                          <tr
                            key={trade.id}
                            className={`hover:bg-muted/40 cursor-pointer border-b transition-colors ${selected?.id === trade.id ? 'bg-muted/50' : ''}`}
                            onClick={() => setSelected(selected?.id === trade.id ? null : trade)}
                          >
                            <td className='text-muted-foreground px-3 py-2 text-xs'>
                              {format(new Date(trade.time), 'MM-dd HH:mm')}
                            </td>
                            <td className='px-3 py-2 font-mono text-xs font-medium'>{trade.symbol}</td>
                            <td className='px-3 py-2'>
                              <Badge variant={ENGINE_BADGE[trade.engine_source] ?? 'outline'} className='text-xs capitalize'>
                                {trade.engine_source}
                              </Badge>
                            </td>
                            <td className='px-3 py-2'>
                              <Badge variant={REGIME_BADGE[trade.regime_at_entry] ?? 'secondary'} className='text-xs'>
                                {trade.regime_at_entry}
                              </Badge>
                            </td>
                            <td className='px-3 py-2 text-right font-mono text-xs'>{trade.size.toFixed(2)}</td>
                            <td className='px-3 py-2 text-right font-mono text-xs'>{trade.entry.toFixed(5)}</td>
                            <td className='px-3 py-2 text-right font-mono text-xs'>
                              {trade.exit !== null ? trade.exit.toFixed(5) : 'open'}
                            </td>
                            <td className={`px-3 py-2 text-right font-mono text-xs ${trade.pnl > 0 ? 'text-green-500' : trade.pnl < 0 ? 'text-red-500' : 'text-muted-foreground'}`}>
                              {trade.pnl > 0 ? '+' : ''}
                              {trade.pnl_pct.toFixed(3)}%
                            </td>
                            <td className='text-muted-foreground px-3 py-2 text-right text-xs'>
                              {holdTime(trade.time, trade.exit_time)}
                            </td>
                          </tr>
                        ))}
                        {filtered.length === 0 && (
                          <tr>
                            <td colSpan={9} className='px-3 py-8'>
                              <DashboardEmptyState
                                title='No trades match the active filters'
                                description='Clear the filters or run the strategy again to generate more trades.'
                              />
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>

              <div className='flex flex-col gap-3 lg:col-span-2'>
                {!selected && (
                  <Card className='h-full'>
                    <CardContent className='flex h-full min-h-[200px] items-center justify-center'>
                      <p className='text-muted-foreground text-sm'>Click a trade to see drilldown details.</p>
                    </CardContent>
                  </Card>
                )}

                {selected && (
                  <>
                    <Card>
                      <CardHeader className='pb-2'>
                        <div className='flex items-center justify-between'>
                          <CardTitle className='text-sm font-medium'>
                            {selected.symbol} · {selected.side.toUpperCase()}
                          </CardTitle>
                          <Badge variant={selected.pnl > 0 ? 'default' : 'destructive'} className='text-xs'>
                            {selected.pnl > 0 ? '+' : ''}
                            {selected.pnl_pct.toFixed(3)}%
                          </Badge>
                        </div>
                        <CardDescription className='text-xs'>
                          {format(new Date(selected.time), 'MMM d HH:mm')}
                          {selected.exit_time && ` -> ${format(new Date(selected.exit_time), 'MMM d HH:mm')}`}
                          {' · '}
                          {holdTime(selected.time, selected.exit_time)}
                        </CardDescription>
                      </CardHeader>
                      <CardContent className='space-y-1.5 text-xs'>
                        <div className='grid grid-cols-2 gap-x-4 gap-y-1'>
                          <div className='flex justify-between'>
                            <span className='text-muted-foreground'>Engine</span>
                            <span className='font-medium capitalize'>{selected.engine_source}</span>
                          </div>
                          <div className='flex justify-between'>
                            <span className='text-muted-foreground'>Regime</span>
                            <Badge variant={REGIME_BADGE[selected.regime_at_entry] ?? 'secondary'} className='text-xs'>
                              {selected.regime_at_entry}
                            </Badge>
                          </div>
                          <div className='flex justify-between'>
                            <span className='text-muted-foreground'>Entry</span>
                            <span className='font-mono'>{selected.entry.toFixed(5)}</span>
                          </div>
                          <div className='flex justify-between'>
                            <span className='text-muted-foreground'>Exit</span>
                            <span className='font-mono'>{selected.exit?.toFixed(5) ?? '—'}</span>
                          </div>
                          <div className='flex justify-between'>
                            <span className='text-muted-foreground'>Stop</span>
                            <span className='font-mono text-red-400'>{selected.stop.toFixed(5)}</span>
                          </div>
                          <div className='flex justify-between'>
                            <span className='text-muted-foreground'>TP</span>
                            <span className='font-mono text-green-400'>{selected.take_profit.toFixed(5)}</span>
                          </div>
                          <div className='flex justify-between'>
                            <span className='text-muted-foreground'>Size</span>
                            <span className='font-mono'>{selected.size.toFixed(2)}</span>
                          </div>
                          <div className='flex justify-between'>
                            <span className='text-muted-foreground'>Close reason</span>
                            <span>{selected.close_reason ?? '—'}</span>
                          </div>
                        </div>
                        {selected.tags.length > 0 && (
                          <div className='flex flex-wrap gap-1 pt-1'>
                            {selected.tags.map((tag) => (
                              <Badge key={tag} variant='outline' className='text-xs'>
                                {tag}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader className='pb-1'>
                        <div className='flex items-center justify-between gap-2'>
                          <CardTitle className='text-xs font-medium'>Price around trade</CardTitle>
                          <ProvenanceBadge source={candlesSource} />
                        </div>
                      </CardHeader>
                      <CardContent className='px-2 pb-2'>
                        {!hasSymbolSpecificCandles ? (
                          <DashboardEmptyState
                            title='Symbol-level price context unavailable'
                            description='The normalized artifacts only contain reference candles, so this trade cannot be plotted on its own symbol series.'
                          />
                        ) : drilldownChart.length === 0 ? (
                          <DashboardEmptyState
                            title='No candles for selected symbol'
                            description='This trade has no matching symbol-level candles in the current artifact set.'
                          />
                        ) : (
                          <ResponsiveContainer width='100%' height={120}>
                            <LineChart data={drilldownChart} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                              <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                              <XAxis dataKey='time' tick={{ fontSize: 8 }} tickLine={false} interval='preserveStartEnd' />
                              <YAxis tick={{ fontSize: 8 }} tickLine={false} domain={['auto', 'auto']} />
                              <Tooltip contentStyle={{ fontSize: 11 }} />
                              <ReferenceLine y={selected.entry} stroke='#22c55e' strokeDasharray='4 2' />
                              {selected.exit && (
                                <ReferenceLine y={selected.exit} stroke='#06b6d4' strokeDasharray='4 2' />
                              )}
                              <ReferenceLine y={selected.stop} stroke='#ef4444' strokeDasharray='2 4' />
                              <Line type='monotone' dataKey='close' stroke='#94a3b8' dot={false} strokeWidth={1.5} />
                            </LineChart>
                          </ResponsiveContainer>
                        )}
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader className='pb-1'>
                        <CardTitle className='text-xs font-medium'>Regime around entry</CardTitle>
                      </CardHeader>
                      <CardContent className='px-2 pb-2'>
                        {drilldownRegime.length > 0 ? (
                          <ResponsiveContainer width='100%' height={100}>
                            <LineChart data={drilldownRegime} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                              <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                              <XAxis dataKey='date' tick={{ fontSize: 8 }} tickLine={false} interval='preserveStartEnd' />
                              <YAxis tick={{ fontSize: 8 }} tickLine={false} unit='%' domain={[0, 100]} />
                              <Tooltip formatter={(value: number) => `${value}%`} contentStyle={{ fontSize: 10 }} />
                              <Line type='monotone' dataKey='TREND' stroke='#22c55e' dot={false} strokeWidth={1.5} />
                              <Line type='monotone' dataKey='CHOP' stroke='#eab308' dot={false} strokeWidth={1.5} />
                              <Line type='monotone' dataKey='RISK_OFF' stroke='#ef4444' dot={false} strokeWidth={1.5} />
                            </LineChart>
                          </ResponsiveContainer>
                        ) : (
                          <DashboardEmptyState
                            title='No regime context available'
                            description='No regime posterior window could be aligned to this trade.'
                          />
                        )}
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader className='pb-1'>
                        <CardTitle className='text-xs font-medium'>Trade Analytics</CardTitle>
                        <div className='pt-1'>
                          <ProvenanceBadge source={analyticsSource} />
                        </div>
                      </CardHeader>
                      <CardContent className='text-xs'>
                        {selectedAnalytics ? (
                          <div className='space-y-1.5'>
                            <CardDescription className='text-xs'>
                              {selectedAnalytics.signal_type ?? '—'}
                            </CardDescription>
                            <div className='grid grid-cols-2 gap-x-4 gap-y-1'>
                              <div className='flex justify-between'>
                                <span className='text-muted-foreground'>Entry efficiency</span>
                                <span className={`font-mono font-medium ${(selectedAnalytics.entry_efficiency ?? 0) >= 0.6 ? 'text-green-500' : 'text-yellow-500'}`}>
                                  {selectedAnalytics.entry_efficiency !== null
                                    ? `${(selectedAnalytics.entry_efficiency * 100).toFixed(1)}%`
                                    : '—'}
                                </span>
                              </div>
                              <div className='flex justify-between'>
                                <span className='text-muted-foreground'>Max adverse</span>
                                <span className='font-mono text-red-400'>
                                  {selectedAnalytics.adverse_excursion !== null
                                    ? `${(selectedAnalytics.adverse_excursion * 100).toFixed(4)}%`
                                    : '—'}
                                </span>
                              </div>
                              <div className='flex justify-between'>
                                <span className='text-muted-foreground'>Max favorable</span>
                                <span className='font-mono text-green-400'>
                                  {selectedAnalytics.favorable_excursion !== null
                                    ? `+${(selectedAnalytics.favorable_excursion * 100).toFixed(4)}%`
                                    : '—'}
                                </span>
                              </div>
                              <div className='flex justify-between'>
                                <span className='text-muted-foreground'>Exit reason</span>
                                <span className='font-mono'>{selectedAnalytics.exit_reason ?? '—'}</span>
                              </div>
                            </div>
                          </div>
                        ) : (
                          <DashboardEmptyState
                            title='Trade analytics unavailable'
                            description='No trade_analytics_rows entry exists for this trade in the current analysis artifact.'
                          />
                        )}
                      </CardContent>
                    </Card>
                  </>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </PageContainer>
  );
}
