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
import { Button } from '@/components/ui/button';
import { DashboardEmptyState } from '@/components/dashboard/empty-state';
import { ProvenanceBadge } from '@/components/dashboard/provenance-badge';
import { fetchRegimeData } from '@/lib/artifacts';
import type { RegimeResponse } from '@/lib/fx-types';
import { IconRefresh } from '@tabler/icons-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';

const REGIME_COLORS: Record<string, string> = {
  TREND: '#22c55e',
  CHOP: '#eab308',
  RISK_OFF: '#ef4444'
};

function shortDate(timestamp: string) {
  try {
    return new Date(timestamp).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric'
    });
  } catch {
    return timestamp.slice(0, 10);
  }
}

export default function RegimePage() {
  const [data, setData] = useState<RegimeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchRegimeData());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const posteriors = data?.regime_posteriors ?? [];
  const allocations = data?.engine_allocations ?? [];
  const occupancy: Record<string, number> = { TREND: 0, CHOP: 0, RISK_OFF: 0 };
  for (const posterior of posteriors) {
    occupancy[posterior.regime_label] = (occupancy[posterior.regime_label] ?? 0) + 1;
  }
  const total = posteriors.length || 1;

  const chartData = posteriors.map((posterior) => ({
    date: shortDate(posterior.timestamp),
    TREND: +(posterior.TREND * 100).toFixed(1),
    CHOP: +(posterior.CHOP * 100).toFixed(1),
    RISK_OFF: +(posterior.RISK_OFF * 100).toFixed(1)
  }));

  const allocationData = allocations.map((allocation) => ({
    date: shortDate(allocation.timestamp),
    Pairs: +(allocation.pairs_alloc * 100).toFixed(1),
    Trend: +(allocation.trend_alloc * 100).toFixed(1)
  }));

  let transitions = 0;
  for (let index = 1; index < posteriors.length; index += 1) {
    if (posteriors[index].regime_label !== posteriors[index - 1].regime_label) {
      transitions += 1;
    }
  }

  const firstTimestamp = posteriors[0]?.timestamp;
  const lastTimestamp = posteriors[posteriors.length - 1]?.timestamp;
  const daySpan =
    firstTimestamp && lastTimestamp
      ? Math.max(
          1,
          (new Date(lastTimestamp).getTime() - new Date(firstTimestamp).getTime()) /
            86400000
        )
      : 1;
  const churnPerDay = posteriors.length > 0 ? +(transitions / daySpan).toFixed(2) : null;

  return (
    <PageContainer>
      <div className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>Regime Monitor</h2>
            <p className='text-muted-foreground text-sm'>
              HMM state occupancy, transition churn, and allocation mix.
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
            title='Regime data unavailable'
            description={error}
            action={
              <Button size='sm' variant='outline' onClick={load}>
                Retry
              </Button>
            }
          />
        )}

        {!error && posteriors.length === 0 && !loading && (
          <DashboardEmptyState
            title='No regime posteriors available'
            description='The current artifact set does not include regime posterior history.'
          />
        )}

        {posteriors.length > 0 && (
          <>
            <div className='grid grid-cols-2 gap-3 sm:grid-cols-4'>
              {(['TREND', 'CHOP', 'RISK_OFF'] as const).map((label) => (
                <Card key={label}>
                  <CardHeader className='pb-1 pt-3'>
                    <CardDescription className='text-xs'>{label}</CardDescription>
                    <CardTitle className='text-2xl font-bold tabular-nums'>
                      {((occupancy[label] / total) * 100).toFixed(1)}%
                    </CardTitle>
                  </CardHeader>
                  <CardContent className='pb-3'>
                    <div className='h-1.5 w-full rounded-full bg-muted'>
                      <div
                        className='h-1.5 rounded-full'
                        style={{
                          width: `${((occupancy[label] / total) * 100).toFixed(1)}%`,
                          backgroundColor: REGIME_COLORS[label]
                        }}
                      />
                    </div>
                    <p className='text-muted-foreground mt-1 text-xs'>
                      {occupancy[label]} of {total} bars
                    </p>
                  </CardContent>
                </Card>
              ))}
              <Card>
                <CardHeader className='pb-1 pt-3'>
                  <CardDescription className='text-xs'>Churn</CardDescription>
                  <CardTitle className='text-2xl font-bold tabular-nums'>
                    {churnPerDay ?? '—'}
                  </CardTitle>
                </CardHeader>
                <CardContent className='pb-3'>
                  <p className='text-muted-foreground text-xs'>
                    {transitions} transitions across the observed window
                  </p>
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader className='pb-2'>
                <CardTitle className='text-sm font-medium'>Regime Timeline</CardTitle>
                <CardDescription>Posterior stack over the current backtest window.</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width='100%' height={240}>
                  <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                    <XAxis dataKey='date' tick={{ fontSize: 10 }} tickLine={false} />
                    <YAxis tick={{ fontSize: 10 }} tickLine={false} domain={[0, 100]} unit='%' />
                    <Tooltip formatter={(value: number) => `${value}%`} />
                    <Legend iconType='circle' iconSize={8} />
                    <Area type='monotone' dataKey='TREND' stackId='1' fill={REGIME_COLORS.TREND} stroke={REGIME_COLORS.TREND} fillOpacity={0.75} />
                    <Area type='monotone' dataKey='CHOP' stackId='1' fill={REGIME_COLORS.CHOP} stroke={REGIME_COLORS.CHOP} fillOpacity={0.75} />
                    <Area type='monotone' dataKey='RISK_OFF' stackId='1' fill={REGIME_COLORS.RISK_OFF} stroke={REGIME_COLORS.RISK_OFF} fillOpacity={0.75} />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </>
        )}

        <Card>
          <CardHeader className='pb-2'>
            <div className='flex items-center justify-between gap-2'>
              <div>
                <CardTitle className='text-sm font-medium'>Engine Allocation</CardTitle>
                <CardDescription>Pairs vs trend allocation over time.</CardDescription>
              </div>
              {data && (
                <ProvenanceBadge source={data.provenance.files.engine_allocations} />
              )}
            </div>
          </CardHeader>
          <CardContent>
            {allocationData.length > 0 ? (
              <ResponsiveContainer width='100%' height={180}>
                <AreaChart data={allocationData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                  <XAxis dataKey='date' tick={{ fontSize: 10 }} tickLine={false} />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} unit='%' />
                  <Tooltip formatter={(value: number) => `${value}%`} />
                  <Legend iconType='circle' iconSize={8} />
                  <Area type='monotone' dataKey='Pairs' fill='#8b5cf6' stroke='#8b5cf6' fillOpacity={0.6} />
                  <Area type='monotone' dataKey='Trend' fill='#06b6d4' stroke='#06b6d4' fillOpacity={0.6} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <DashboardEmptyState
                title='Allocation history unavailable'
                description='The active artifact set does not contain engine allocation history for this run.'
              />
            )}
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
