'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { PriceChart } from '@/components/charts/price-chart';
import PageContainer from '@/components/layout/page-container';
import { DashboardEmptyState } from '@/components/dashboard/empty-state';
import { ProvenanceBadge } from '@/components/dashboard/provenance-badge';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { fetchAlgoState, fetchAnalysisData } from '@/lib/artifacts';
import type { AlgoState, AnalysisResponse, IndicatorSnapshot } from '@/lib/fx-types';
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

function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—';
  }
  return value.toFixed(digits);
}

function buildOverlayData(indicators: IndicatorSnapshot[]) {
  return indicators.slice(-120).map((row) => ({
    time: row.timestamp.slice(5, 16),
    close: row.close,
    smaFast: row.sma_fast,
    smaSlow: row.sma_slow
  }));
}

function buildMacdData(indicators: IndicatorSnapshot[]) {
  return indicators.slice(-120).map((row) => ({
    time: row.timestamp.slice(5, 16),
    macd: row.macd_line,
    signal: row.macd_signal,
    histogram: row.macd_histogram,
    rsi: row.rsi
  }));
}

export default function TrendPage() {
  const [state, setState] = useState<AlgoState | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextState, nextAnalysis] = await Promise.all([
        fetchAlgoState(),
        fetchAnalysisData()
      ]);
      setState(nextState);
      setAnalysis(nextAnalysis);
      setSelectedSymbol((current) => {
        const candidates = [
          current,
          nextState.manifest.active_symbol,
          nextState.manifest.symbols[0],
          nextAnalysis.trend_decisions[0]?.symbol,
          nextAnalysis.indicator_snapshots[0]?.symbol,
          nextAnalysis.signals_sample[0]?.symbol
        ].filter((value): value is string => Boolean(value));
        return candidates[0] ?? '';
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const availableSymbols = useMemo(
    () =>
      Array.from(
        new Set([
          ...(state?.manifest.symbols ?? []),
          ...(state?.candles.map((candle) => candle.symbol ?? '').filter(Boolean) ?? []),
          ...(analysis?.signals_sample.map((signal) => signal.symbol).filter(Boolean) ?? []),
          ...(analysis?.trend_decisions.map((decision) => decision.symbol).filter(Boolean) ?? []),
          ...(analysis?.indicator_snapshots
            .map((snapshot) => snapshot.symbol)
            .filter(Boolean) ?? [])
        ])
      ),
    [analysis, state]
  );
  const resolvedSymbol =
    (selectedSymbol && availableSymbols.includes(selectedSymbol) && selectedSymbol) ||
    state?.manifest.active_symbol ||
    availableSymbols[0] ||
    '';
  const symbolCandles = (state?.candles ?? []).filter(
    (candle) => (candle.symbol ?? resolvedSymbol) === resolvedSymbol
  );
  const symbolIndicators = (analysis?.indicator_snapshots ?? []).filter(
    (snapshot) => snapshot.symbol === resolvedSymbol
  );
  const latestIndicator = symbolIndicators[symbolIndicators.length - 1] ?? null;
  const trendDecisions = (analysis?.trend_decisions ?? [])
    .filter((decision) => decision.symbol === resolvedSymbol)
    .slice(-12)
    .reverse();
  const overlayData = buildOverlayData(symbolIndicators);
  const macdData = buildMacdData(symbolIndicators);

  return (
    <PageContainer>
      <div className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>Trend Monitor</h2>
            <p className='text-muted-foreground text-sm'>
              Candle replay, indicator evidence, and decision reasons for the selected symbol.
            </p>
          </div>
          <div className='flex items-center gap-2'>
            {analysis && <ProvenanceBadge source={analysis.provenance.overall} />}
            {state && <ProvenanceBadge source={state.provenance.files.candles} />}
            <Button size='sm' variant='outline' onClick={load} disabled={loading}>
              <IconRefresh className='mr-1 h-3 w-3' />
              Refresh
            </Button>
          </div>
        </div>

        {state?.manifest.simulated_market_data && (
          <div className='rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200'>
            Local paper is using simulated historical market data (`lean_history`). Trend
            decisions are current, but prices are not broker-routed live fills.
          </div>
        )}

        {error && (
          <DashboardEmptyState
            title='Trend data unavailable'
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
            <div className='grid grid-cols-1 gap-4 lg:grid-cols-5'>
              <Card>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>Model Version</CardTitle>
                </CardHeader>
                <CardContent className='font-mono text-sm'>
                  {analysis?.trend_model_meta?.model_version ?? '—'}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>Train Window</CardTitle>
                </CardHeader>
                <CardContent className='font-mono text-sm'>
                  {analysis?.trend_model_meta
                    ? `${analysis.trend_model_meta.training_window_days}d`
                    : '—'}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>Last Retrain</CardTitle>
                </CardHeader>
                <CardContent className='font-mono text-sm'>
                  {analysis?.trend_model_meta?.last_retrain_time?.slice(0, 19) ?? '—'}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>Calibration</CardTitle>
                </CardHeader>
                <CardContent className='font-mono text-sm'>
                  {fmtNumber(analysis?.trend_model_meta?.calibration_score, 3)}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>Schema Hash</CardTitle>
                </CardHeader>
                <CardContent className='font-mono text-sm'>
                  {analysis?.trend_model_meta?.feature_schema_hash?.slice(0, 12) ?? '—'}
                </CardContent>
              </Card>
            </div>

            <div className='grid grid-cols-1 gap-4 lg:grid-cols-3'>
              <Card className='lg:col-span-2'>
                <CardHeader className='pb-2'>
                  <div className='flex flex-wrap items-center justify-between gap-2'>
                    <div>
                      <CardTitle className='text-sm font-medium'>Candle Replay</CardTitle>
                      <CardDescription>
                        Local-paper candles for the selected symbol.
                      </CardDescription>
                    </div>
                    <div className='flex items-center gap-2'>
                      <select
                        value={resolvedSymbol}
                        onChange={(event) => setSelectedSymbol(event.target.value)}
                        aria-label='Trend symbol selector'
                        className='border-input bg-background ring-offset-background focus-visible:ring-ring h-9 rounded-md border px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2'
                      >
                        {availableSymbols.map((symbol) => (
                          <option key={symbol} value={symbol}>
                            {symbol}
                          </option>
                        ))}
                      </select>
                      {state && <ProvenanceBadge source={state.provenance.files.candles} />}
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {symbolCandles.length > 0 ? (
                    <PriceChart candles={symbolCandles} symbol={resolvedSymbol} />
                  ) : (
                    <DashboardEmptyState
                      title='Trend chart unavailable'
                      description='The current session artifact set does not have candle data for the selected symbol.'
                    />
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className='pb-2'>
                  <div className='flex items-center justify-between gap-2'>
                    <div>
                      <CardTitle className='text-sm font-medium'>Latest Indicator Snapshot</CardTitle>
                      <CardDescription>Observability-only indicator evidence.</CardDescription>
                    </div>
                    {analysis && (
                      <ProvenanceBadge source={analysis.provenance.files.indicator_snapshots} />
                    )}
                  </div>
                </CardHeader>
                <CardContent>
                  {latestIndicator ? (
                    <div className='space-y-3'>
                      <div className='grid grid-cols-2 gap-x-4 gap-y-2 text-xs'>
                        <span className='text-muted-foreground'>Timestamp</span>
                        <span className='text-right font-mono'>
                          {latestIndicator.timestamp.slice(0, 19)}
                        </span>
                        <span className='text-muted-foreground'>Close</span>
                        <span className='text-right font-mono'>
                          {fmtNumber(latestIndicator.close, 5)}
                        </span>
                        <span className='text-muted-foreground'>SMA Fast / Slow</span>
                        <span className='text-right font-mono'>
                          {fmtNumber(latestIndicator.sma_fast, 5)} /{' '}
                          {fmtNumber(latestIndicator.sma_slow, 5)}
                        </span>
                        <span className='text-muted-foreground'>RSI</span>
                        <span className='text-right font-mono'>
                          {fmtNumber(latestIndicator.rsi, 2)}
                        </span>
                        <span className='text-muted-foreground'>Realized Vol</span>
                        <span className='text-right font-mono'>
                          {fmtNumber(latestIndicator.realized_vol, 4)}
                        </span>
                        <span className='text-muted-foreground'>SMA Crossover</span>
                        <span className='text-right font-mono'>
                          {fmtNumber(latestIndicator.sma_crossover, 4)}
                        </span>
                        <span className='text-muted-foreground'>MACD Histogram</span>
                        <span className='text-right font-mono'>
                          {fmtNumber(latestIndicator.macd_histogram, 5)}
                        </span>
                      </div>
                      <div className='flex flex-wrap gap-2'>
                        <Badge
                          variant={latestIndicator.macd_bullish_divergence ? 'default' : 'outline'}
                        >
                          Bullish divergence
                        </Badge>
                        <Badge
                          variant={
                            latestIndicator.macd_bearish_divergence ? 'destructive' : 'outline'
                          }
                        >
                          Bearish divergence
                        </Badge>
                      </div>
                    </div>
                  ) : (
                    <DashboardEmptyState
                      title='Indicator snapshot unavailable'
                      description='No indicator telemetry was emitted for the selected symbol.'
                    />
                  )}
                </CardContent>
              </Card>
            </div>

            <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
              <Card>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>Trend Overlay</CardTitle>
                  <CardDescription>Close with SMA fast and SMA slow.</CardDescription>
                </CardHeader>
                <CardContent>
                  {overlayData.length > 0 ? (
                    <ResponsiveContainer width='100%' height={240}>
                      <LineChart data={overlayData} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                        <XAxis dataKey='time' tick={{ fontSize: 10 }} tickLine={false} />
                        <YAxis tick={{ fontSize: 10 }} tickLine={false} domain={['auto', 'auto']} />
                        <Tooltip />
                        <Line type='monotone' dataKey='close' stroke='#0ea5e9' dot={false} strokeWidth={1.6} />
                        <Line type='monotone' dataKey='smaFast' stroke='#22c55e' dot={false} strokeWidth={1.2} />
                        <Line type='monotone' dataKey='smaSlow' stroke='#f59e0b' dot={false} strokeWidth={1.2} />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <DashboardEmptyState
                      title='Overlay unavailable'
                      description='The selected symbol has no indicator history yet.'
                    />
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>MACD and RSI</CardTitle>
                  <CardDescription>Decision-support telemetry from the trend engine.</CardDescription>
                </CardHeader>
                <CardContent>
                  {macdData.length > 0 ? (
                    <ResponsiveContainer width='100%' height={240}>
                      <LineChart data={macdData} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                        <XAxis dataKey='time' tick={{ fontSize: 10 }} tickLine={false} />
                        <YAxis yAxisId='macd' tick={{ fontSize: 10 }} tickLine={false} />
                        <YAxis
                          yAxisId='rsi'
                          orientation='right'
                          tick={{ fontSize: 10 }}
                          tickLine={false}
                          domain={[0, 100]}
                        />
                        <Tooltip />
                        <ReferenceLine yAxisId='macd' y={0} stroke='#64748b' strokeDasharray='4 4' />
                        <ReferenceLine yAxisId='rsi' y={70} stroke='#ef4444' strokeDasharray='4 4' />
                        <ReferenceLine yAxisId='rsi' y={30} stroke='#22c55e' strokeDasharray='4 4' />
                        <Line yAxisId='macd' type='monotone' dataKey='macd' stroke='#8b5cf6' dot={false} strokeWidth={1.4} />
                        <Line yAxisId='macd' type='monotone' dataKey='signal' stroke='#f97316' dot={false} strokeWidth={1.2} />
                        <Line yAxisId='macd' type='monotone' dataKey='histogram' stroke='#06b6d4' dot={false} strokeWidth={1.1} />
                        <Line yAxisId='rsi' type='monotone' dataKey='rsi' stroke='#eab308' dot={false} strokeWidth={1.1} />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <DashboardEmptyState
                      title='MACD / RSI unavailable'
                      description='The selected symbol has no MACD or RSI history yet.'
                    />
                  )}
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader className='pb-2'>
                <div className='flex items-center justify-between gap-2'>
                  <div>
                    <CardTitle className='text-sm font-medium'>Recent Trend Decisions</CardTitle>
                    <CardDescription>
                      Final long/short/flat outcomes with thresholds and observed divergence.
                    </CardDescription>
                  </div>
                  {analysis && (
                    <ProvenanceBadge source={analysis.provenance.files.trend_decisions} />
                  )}
                </div>
              </CardHeader>
              <CardContent>
                {trendDecisions.length > 0 ? (
                  <div className='overflow-auto'>
                    <table className='w-full text-sm'>
                      <thead>
                        <tr className='text-muted-foreground border-b text-xs'>
                          <th className='pb-2 text-left font-medium'>Time</th>
                          <th className='pb-2 text-left font-medium'>Direction</th>
                          <th className='pb-2 text-right font-medium'>Confidence</th>
                          <th className='pb-2 text-right font-medium'>p_up / p_down</th>
                          <th className='pb-2 text-right font-medium'>Threshold</th>
                          <th className='pb-2 text-left font-medium'>Reason</th>
                          <th className='pb-2 text-left font-medium'>Divergence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trendDecisions.map((decision) => (
                          <tr key={`${decision.timestamp}-${decision.symbol}`} className='border-b text-xs'>
                            <td className='py-2 font-mono'>{decision.timestamp.slice(0, 19)}</td>
                            <td className='py-2'>
                              <Badge
                                variant={
                                  decision.direction === 'long'
                                    ? 'default'
                                    : decision.direction === 'short'
                                      ? 'destructive'
                                      : 'secondary'
                                }
                              >
                                {decision.direction}
                              </Badge>
                            </td>
                            <td className='py-2 text-right font-mono'>
                              {fmtNumber(decision.confidence, 3)}
                            </td>
                            <td className='py-2 text-right font-mono'>
                              {fmtNumber(decision.trend_p_up, 3)} / {fmtNumber(decision.trend_p_down, 3)}
                            </td>
                            <td className='py-2 text-right font-mono'>
                              {fmtNumber(decision.decision_threshold, 3)}
                            </td>
                            <td className='py-2'>{decision.decision_reason}</td>
                            <td className='py-2'>
                              <Badge variant={decision.observed_divergence === 'none' ? 'outline' : 'secondary'}>
                                {decision.observed_divergence}
                              </Badge>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <DashboardEmptyState
                    title='No trend decisions'
                    description='The selected symbol has no emitted trend decision rows in the current session artifact set.'
                  />
                )}
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </PageContainer>
  );
}
