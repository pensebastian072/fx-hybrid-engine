'use client';

import { useCallback, useEffect, useState } from 'react';
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
import { DashboardEmptyState } from '@/components/dashboard/empty-state';
import { ProvenanceBadge } from '@/components/dashboard/provenance-badge';
import { fetchPairsData } from '@/lib/artifacts';
import type { PairHistory, PairsResponse } from '@/lib/fx-types';
import { IconRefresh } from '@tabler/icons-react';
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

const STATE_BADGE: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  TRADABLE: 'default',
  WATCH: 'secondary',
  DISABLED: 'destructive'
};

type DetailTab = 'zscore' | 'pvalue' | 'beta' | 'events';

function fmt(value: number | null, decimals = 4): string {
  if (value === null || value === undefined) {
    return '—';
  }
  return value.toFixed(decimals);
}

export default function PairsPage() {
  const [data, setData] = useState<PairsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<DetailTab>('zscore');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchPairsData());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const pairs = data?.pairs ?? [];
  const selectedPair = pairs.find((pair) => pair.pair_id === selected) ?? null;
  const history: PairHistory | null = selected ? data?.pair_history[selected] ?? null : null;
  const pairHistorySource = data?.provenance.files.pair_history ?? 'missing';
  const zscoreSeries = history?.zscore_series ?? [];
  const pvalueSeries = history?.scan_history.filter((point) => point.pvalue !== null) ?? [];
  const betaSeries = history?.scan_history.filter((point) => point.beta !== null) ?? [];
  const stateEvents = history?.state_events ?? [];
  const tabAvailability: Record<DetailTab, boolean> = {
    zscore: zscoreSeries.length > 0,
    pvalue: pvalueSeries.length > 0,
    beta: betaSeries.length > 0,
    events: stateEvents.length > 0
  };

  const tradable = pairs.filter((pair) => pair.state === 'TRADABLE').length;
  const watch = pairs.filter((pair) => pair.state === 'WATCH').length;
  const disabled = pairs.filter((pair) => pair.state === 'DISABLED').length;
  const tradeUniverseCount = pairs.filter((pair) => pair.in_trade_universe).length;
  const observeOnlyCount = pairs.filter((pair) => !pair.in_trade_universe).length;
  const tabs: { id: DetailTab; label: string }[] = [
    { id: 'zscore', label: 'Z-Score' },
    { id: 'pvalue', label: 'P-Value' },
    { id: 'beta', label: 'Beta' },
    { id: 'events', label: 'Events' }
  ];

  const historyUnavailableCopy =
    pairHistorySource === 'mock'
      ? 'History was not emitted for the latest normalized artifact set. Showing demo fallback history instead.'
      : data?.provenance.overall === 'run_history'
        ? 'History was not emitted for the selected historical run, so the missing detail tabs stay unavailable.'
        : 'History was not emitted for the current session artifact set, so the missing detail tabs stay unavailable.';

  return (
    <PageContainer>
      <div className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>Pairs Diagnostics</h2>
            <p className='text-muted-foreground text-sm'>
              {pairs.length} scanned pairs with status, cointegration strength, and drilldowns.
            </p>
          </div>
          <div className='flex items-center gap-2'>
            {data && <ProvenanceBadge source={data.provenance.overall} />}
            <Button size='sm' variant='outline' onClick={load} disabled={loading}>
              <IconRefresh className='mr-1 h-3 w-3' />
              Refresh
            </Button>
          </div>
        </div>

        {error && (
          <DashboardEmptyState
            title='Pairs data unavailable'
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
            <div className='flex flex-wrap gap-3'>
              <Badge variant='default'>{tradable} TRADABLE</Badge>
              <Badge variant='secondary'>{watch} WATCH</Badge>
              <Badge variant='destructive'>{disabled} DISABLED</Badge>
              <Badge variant='outline'>{tradeUniverseCount} trade-universe</Badge>
              <Badge variant='outline'>{observeOnlyCount} observe-only</Badge>
              {data && <ProvenanceBadge source={data.provenance.files.pair_history} />}
            </div>

            <div className='grid grid-cols-1 gap-4 lg:grid-cols-3'>
              <Card className='lg:col-span-2'>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>Pair Status</CardTitle>
                  <CardDescription>Select a row to inspect history when available.</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className='overflow-auto'>
                    <table className='w-full text-sm'>
                      <thead>
                        <tr className='text-muted-foreground border-b text-xs'>
                          <th className='pb-2 text-left font-medium'>Pair</th>
                          <th className='pb-2 text-left font-medium'>Status</th>
                          <th className='pb-2 text-right font-medium'>p-value</th>
                          <th className='pb-2 text-right font-medium'>Beta</th>
                          <th className='pb-2 text-right font-medium'>|Z| p95</th>
                          <th className='pb-2 text-right font-medium'>Trades</th>
                          <th className='pb-2 text-left font-medium'>Universe</th>
                          <th className='pb-2 text-left font-medium'>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pairs.map((pair) => (
                          <tr
                            key={pair.pair_id}
                            className={`hover:bg-muted/40 cursor-pointer border-b transition-colors ${selected === pair.pair_id ? 'bg-muted/50' : ''}`}
                            onClick={() => {
                              setSelected(selected === pair.pair_id ? null : pair.pair_id);
                              setTab('zscore');
                            }}
                          >
                            <td className='py-2 font-mono text-xs'>{pair.pair_id}</td>
                            <td className='py-2'>
                              <Badge variant={STATE_BADGE[pair.state] ?? 'outline'} className='text-xs'>
                                {pair.state}
                              </Badge>
                            </td>
                            <td className='py-2 text-right font-mono text-xs'>{fmt(pair.latest_pvalue, 4)}</td>
                            <td className='py-2 text-right font-mono text-xs'>{fmt(pair.latest_beta, 3)}</td>
                            <td className='py-2 text-right font-mono text-xs'>{fmt(pair.latest_z_abs_p95, 2)}</td>
                            <td className='py-2 text-right font-mono text-xs'>{pair.trade_count}</td>
                            <td className='py-2'>
                              <Badge
                                variant={pair.in_trade_universe ? 'default' : 'outline'}
                                className='text-[10px]'
                              >
                                {pair.in_trade_universe ? 'TRADE' : 'OBSERVE'}
                              </Badge>
                            </td>
                            <td className='text-muted-foreground py-2 text-xs'>{pair.primary_reason || '—'}</td>
                          </tr>
                        ))}
                        {pairs.length === 0 && (
                          <tr>
                            <td colSpan={8} className='py-8'>
                              <DashboardEmptyState
                                title='No pairs diagnostics available'
                                description='The current artifact set does not include pairs diagnostics.'
                              />
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className='pb-2'>
                  <div className='flex items-start justify-between gap-2'>
                    <div>
                      <CardTitle className='text-sm font-medium'>
                        {selectedPair ? selectedPair.pair_id : 'Select a pair'}
                      </CardTitle>
                      {selectedPair && (
                        <CardDescription className='flex items-center gap-2 pt-1'>
                          <Badge variant={STATE_BADGE[selectedPair.state] ?? 'outline'} className='text-xs'>
                            {selectedPair.state}
                          </Badge>
                          <Badge
                            variant={selectedPair.in_trade_universe ? 'default' : 'outline'}
                            className='text-xs'
                          >
                            {selectedPair.in_trade_universe ? 'TRADE' : 'OBSERVE'}
                          </Badge>
                          <span>{selectedPair.primary_reason}</span>
                        </CardDescription>
                      )}
                    </div>
                    <ProvenanceBadge source={pairHistorySource} />
                  </div>
                </CardHeader>
                <CardContent>
                  {!selectedPair && (
                    <DashboardEmptyState
                      title='No pair selected'
                      description='Choose a pair from the table to inspect its statistics and history.'
                    />
                  )}

                  {selectedPair && (
                    <div className='flex flex-col gap-3'>
                      <div className='grid grid-cols-2 gap-x-4 gap-y-1 text-xs'>
                        <span className='text-muted-foreground'>p-value</span>
                        <span className='text-right font-mono'>{fmt(selectedPair.latest_pvalue, 4)}</span>
                        <span className='text-muted-foreground'>Beta</span>
                        <span className='text-right font-mono'>{fmt(selectedPair.latest_beta, 4)}</span>
                        <span className='text-muted-foreground'>Spread Std</span>
                        <span className='text-right font-mono'>{fmt(selectedPair.latest_spread_std, 6)}</span>
                        <span className='text-muted-foreground'>|Z| p95</span>
                        <span className='text-right font-mono'>{fmt(selectedPair.latest_z_abs_p95, 2)}</span>
                        <span className='text-muted-foreground'>Trades</span>
                        <span className='text-right font-mono'>{selectedPair.trade_count}</span>
                      </div>

                      <div className='flex gap-1 border-b pb-1'>
                        {tabs.map((tabOption) => (
                          <button
                            key={tabOption.id}
                            onClick={() => setTab(tabOption.id)}
                            disabled={!history || !tabAvailability[tabOption.id]}
                            className={`rounded-sm px-2 py-1 text-xs font-medium transition-colors ${tab === tabOption.id ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'} ${!history || !tabAvailability[tabOption.id] ? 'cursor-not-allowed opacity-50' : ''}`}
                          >
                            {tabOption.label}
                          </button>
                        ))}
                      </div>

                      {!history && (
                        <DashboardEmptyState
                          title='Pair history unavailable'
                          description={historyUnavailableCopy}
                        />
                      )}

                      {history && tab === 'zscore' && (
                        zscoreSeries.length > 0 ? (
                          <div>
                            <p className='text-muted-foreground mb-1 text-xs'>Z-Score with +/-2.0 entry bands</p>
                            <ResponsiveContainer width='100%' height={180}>
                              <LineChart data={zscoreSeries} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                                <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                                <XAxis dataKey='date' tick={{ fontSize: 8 }} tickLine={false} interval={6} />
                                <YAxis tick={{ fontSize: 9 }} domain={[-3, 3]} />
                                <Tooltip formatter={(value: number) => value.toFixed(2)} />
                                <ReferenceLine y={2} stroke='#22c55e' strokeDasharray='4 2' />
                                <ReferenceLine y={-2} stroke='#22c55e' strokeDasharray='4 2' />
                                <ReferenceLine y={0} stroke='#888' strokeWidth={0.5} />
                                <Line type='monotone' dataKey='zscore' stroke='#06b6d4' dot={false} strokeWidth={1.5} />
                              </LineChart>
                            </ResponsiveContainer>
                          </div>
                        ) : (
                          <DashboardEmptyState
                            title='No z-score series'
                            description='The current session artifact set did not emit z-score history for the selected pair.'
                          />
                        )
                      )}

                      {history && tab === 'pvalue' && (
                        pvalueSeries.length > 0 ? (
                          <div>
                            <p className='text-muted-foreground mb-1 text-xs'>P-Value history</p>
                            <ResponsiveContainer width='100%' height={180}>
                              <LineChart data={pvalueSeries} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                                <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                                <XAxis dataKey='date' tick={{ fontSize: 8 }} tickLine={false} interval={2} />
                                <YAxis tick={{ fontSize: 9 }} domain={[0, 0.35]} />
                                <Tooltip formatter={(value: number) => value.toFixed(4)} />
                                <ReferenceLine y={0.08} stroke='#22c55e' strokeDasharray='4 2' />
                                <ReferenceLine y={0.15} stroke='#eab308' strokeDasharray='4 2' />
                                <ReferenceLine y={0.25} stroke='#ef4444' strokeDasharray='4 2' />
                                <Line type='monotone' dataKey='pvalue' stroke='#8b5cf6' dot={{ r: 3 }} strokeWidth={1.5} />
                              </LineChart>
                            </ResponsiveContainer>
                          </div>
                        ) : (
                          <DashboardEmptyState
                            title='No p-value history'
                            description='The current session artifact set did not emit p-value scan history for the selected pair.'
                          />
                        )
                      )}

                      {history && tab === 'beta' && (
                        betaSeries.length > 0 ? (
                          <div>
                            <p className='text-muted-foreground mb-1 text-xs'>Beta drift over time</p>
                            <ResponsiveContainer width='100%' height={180}>
                              <LineChart data={betaSeries} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                                <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                                <XAxis dataKey='date' tick={{ fontSize: 8 }} tickLine={false} interval={2} />
                                <YAxis tick={{ fontSize: 9 }} />
                                <Tooltip formatter={(value: number) => value.toFixed(4)} />
                                <Line type='monotone' dataKey='beta' stroke='#f97316' dot={{ r: 3 }} strokeWidth={1.5} />
                              </LineChart>
                            </ResponsiveContainer>
                          </div>
                        ) : (
                          <DashboardEmptyState
                            title='No beta history'
                            description='The current session artifact set did not emit beta drift history for the selected pair.'
                          />
                        )
                      )}

                      {history && tab === 'events' && (
                        <div className='space-y-2'>
                          {stateEvents.length > 0 ? (
                            stateEvents.map((event, index) => (
                              <div key={`${event.date}-${index}`} className='rounded-md border p-2'>
                                <p className='text-xs font-medium'>{event.event}</p>
                                <p className='text-muted-foreground text-xs'>
                                  {event.date} - {event.reason}
                                </p>
                              </div>
                            ))
                          ) : (
                            <DashboardEmptyState
                              title='No state transitions recorded'
                              description='This pair history has no recorded state transition events.'
                            />
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </>
        )}
      </div>
    </PageContainer>
  );
}
