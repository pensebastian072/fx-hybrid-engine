'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
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
import {
  fetchAnalysisData,
  fetchWalkforwardData
} from '@/lib/artifacts';
import type {
  AnalysisResponse,
  WalkforwardResponse,
  WfSplitMetrics
} from '@/lib/fx-types';
import { IconCheck, IconRefresh, IconX } from '@tabler/icons-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';

type SectionKey = 'overview' | 'attribution' | 'proof' | 'model';

const MODE_COLORS: Record<string, string> = {
  hybrid: '#22c55e',
  pairs_only: '#8b5cf6',
  trend_only: '#06b6d4'
};

const SECTION_OPTIONS: { key: SectionKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'attribution', label: 'Attribution' },
  { key: 'proof', label: 'Proof & Robustness' },
  { key: 'model', label: 'Model Diagnostics' }
];

function pct(value: number | undefined | null) {
  if (value === undefined || value === null) {
    return '—';
  }
  return `${(value * 100).toFixed(2)}%`;
}

function fmt(value: number | undefined | null, digits = 2) {
  if (value === undefined || value === null) {
    return '—';
  }
  return value.toFixed(digits);
}

function WalkforwardPageContent() {
  const searchParams = useSearchParams();
  const [section, setSection] = useState<SectionKey>('overview');
  const [walkforward, setWalkforward] = useState<WalkforwardResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const nextSection = searchParams.get('section');
    if (nextSection === 'attribution' || nextSection === 'proof' || nextSection === 'model' || nextSection === 'overview') {
      setSection(nextSection);
    }
  }, [searchParams]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [walkforwardData, analysisData] = await Promise.all([
        fetchWalkforwardData(),
        fetchAnalysisData()
      ]);
      setWalkforward(walkforwardData);
      setAnalysis(analysisData);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const scorecardRows = useMemo(() => {
    const modes = ['hybrid', 'pairs_only', 'trend_only'];
    const byMode = walkforward?.walkforward_metrics?.by_mode ?? {};
    return modes.map((mode) => {
      const split = byMode[mode]?.[0] as WfSplitMetrics | undefined;
      return {
        mode,
        total_return: split?.total_return,
        sharpe: split?.sharpe,
        max_drawdown: split?.max_drawdown,
        win_rate: split?.win_rate,
        trades: split?.trades
      };
    });
  }, [walkforward]);

  const attributionByEngineRegime = useMemo(() => {
    return (walkforward?.pnl_attribution?.engine_x_regime ?? []).map((row) => ({
      name: `${row.engine_source ?? '—'}/${row.entry_regime ?? '—'}`,
      pnl: row.total_pnl !== undefined ? +(row.total_pnl * 100).toFixed(3) : 0,
      win_rate: row.win_rate !== undefined ? +(row.win_rate * 100).toFixed(1) : 0,
      n: row.n_trades ?? 0
    }));
  }, [walkforward]);

  const attributionByEngine = useMemo(() => {
    return (walkforward?.pnl_attribution?.by_engine ?? []).map((row) => ({
      name: row.engine_source ?? '—',
      pnl: row.total_pnl !== undefined ? +(row.total_pnl * 100).toFixed(3) : 0
    }));
  }, [walkforward]);

  const attributionByRegime = useMemo(() => {
    return (walkforward?.pnl_attribution?.by_regime ?? []).map((row) => ({
      name: row.entry_regime ?? '—',
      pnl: row.total_pnl !== undefined ? +(row.total_pnl * 100).toFixed(3) : 0
    }));
  }, [walkforward]);

  const robustnessCostSweep = useMemo(() => {
    return (walkforward?.robustness?.cost_sweep ?? []).map((row) => ({
      scenario: row.scenario,
      sharpe: +row.sharpe.toFixed(3),
      total_return: +(row.total_return * 100).toFixed(2)
    }));
  }, [walkforward]);

  const confidenceScatter = useMemo(() => {
    return (analysis?.analysis?.confidence_buckets ?? []).map((bucket) => ({
      confidence: bucket.avg_confidence,
      win_rate: +(bucket.win_rate * 100).toFixed(1),
      trades: bucket.n,
      bucket: bucket.bucket
    }));
  }, [analysis]);

  return (
    <PageContainer>
      <div className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>Walk-Forward Research</h2>
            <p className='text-muted-foreground text-sm'>
              Promotion gate, attribution, robustness, and trend-model diagnostics.
            </p>
          </div>
          <div className='flex items-center gap-2'>
            {walkforward && <ProvenanceBadge source={walkforward.provenance.overall} />}
            <Button size='sm' variant='outline' onClick={load} disabled={loading}>
              <IconRefresh className='mr-1 h-3 w-3' />
              Refresh
            </Button>
          </div>
        </div>

        <div className='flex flex-wrap gap-2'>
          {SECTION_OPTIONS.map((option) => (
            <Button
              key={option.key}
              size='sm'
              variant={section === option.key ? 'default' : 'outline'}
              onClick={() => setSection(option.key)}
            >
              {option.label}
            </Button>
          ))}
        </div>

        {error && (
          <DashboardEmptyState
            title='Walk-forward data unavailable'
            description={error}
            action={
              <Button size='sm' variant='outline' onClick={load}>
                Retry
              </Button>
            }
          />
        )}

        {!error && section === 'overview' && (
          <>
            {walkforward?.promotion_decision ? (
              <Card className={walkforward.promotion_decision.pass ? 'border-green-500/40 bg-green-500/5' : 'border-red-500/40 bg-red-500/5'}>
                <CardHeader className='pb-2'>
                  <div className='flex items-center justify-between'>
                    <div>
                      <CardTitle className='text-sm font-medium'>Promotion Decision</CardTitle>
                      <CardDescription>
                        Ladder stage {walkforward.promotion_decision.ladder.current_stage}{' '}
                        {'->'} {walkforward.promotion_decision.ladder.next_stage}
                      </CardDescription>
                    </div>
                    <Badge variant={walkforward.promotion_decision.pass ? 'default' : 'destructive'}>
                      {walkforward.promotion_decision.pass ? 'GO' : 'NO-GO'}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className='flex flex-wrap gap-4 text-sm'>
                  <div>
                    <p className='text-muted-foreground text-xs'>Action</p>
                    <p className='font-mono font-semibold capitalize'>
                      {walkforward.promotion_decision.ladder.action}
                    </p>
                  </div>
                  <div>
                    <p className='text-muted-foreground text-xs'>Failed Gates</p>
                    <p>{walkforward.promotion_decision.failed_reasons.length || 0}</p>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <DashboardEmptyState
                title='Promotion decision unavailable'
                description='No promotion_decision artifact is available for the current run.'
              />
            )}

            <Card>
              <CardHeader className='pb-2'>
                <CardTitle className='text-sm font-medium'>Strategy Scorecard</CardTitle>
                <CardDescription>Hybrid vs pairs-only vs trend-only on split 0.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className='overflow-auto'>
                  <table className='w-full text-sm'>
                    <thead>
                      <tr className='text-muted-foreground border-b text-xs'>
                        <th className='pb-2 text-left font-medium'>Mode</th>
                        <th className='pb-2 text-right font-medium'>Return</th>
                        <th className='pb-2 text-right font-medium'>Sharpe</th>
                        <th className='pb-2 text-right font-medium'>Max DD</th>
                        <th className='pb-2 text-right font-medium'>Win Rate</th>
                        <th className='pb-2 text-right font-medium'>Trades</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scorecardRows.map((row) => (
                        <tr key={row.mode} className='border-b'>
                          <td className='py-2'>
                            <div className='flex items-center gap-2'>
                              <div className='h-2.5 w-2.5 rounded-full' style={{ backgroundColor: MODE_COLORS[row.mode] }} />
                              <span className='font-medium capitalize'>{row.mode.replace('_', ' ')}</span>
                            </div>
                          </td>
                          <td className='py-2 text-right font-mono text-xs'>{pct(row.total_return)}</td>
                          <td className='py-2 text-right font-mono text-xs'>{fmt(row.sharpe)}</td>
                          <td className='py-2 text-right font-mono text-xs text-orange-400'>{pct(row.max_drawdown)}</td>
                          <td className='py-2 text-right font-mono text-xs'>{pct(row.win_rate)}</td>
                          <td className='py-2 text-right font-mono text-xs'>{row.trades ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className='pb-2'>
                <CardTitle className='text-sm font-medium'>Robustness Cost Sweep</CardTitle>
                <CardDescription>Sharpe and total return sensitivity to trading costs.</CardDescription>
              </CardHeader>
              <CardContent>
                {robustnessCostSweep.length > 0 ? (
                  <ResponsiveContainer width='100%' height={220}>
                    <LineChart data={robustnessCostSweep} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                      <XAxis dataKey='scenario' tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 10 }} />
                      <Tooltip />
                      <Legend iconType='circle' iconSize={8} />
                      <Line type='monotone' dataKey='sharpe' stroke='#22c55e' dot />
                      <Line type='monotone' dataKey='total_return' stroke='#06b6d4' dot />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <DashboardEmptyState
                    title='No robustness sweep available'
                    description='The current run does not include robustness cost-sweep outputs.'
                  />
                )}
              </CardContent>
            </Card>
          </>
        )}

        {!error && section === 'attribution' && (
          <>
            <Card>
              <CardHeader className='pb-2'>
                <div className='flex items-center justify-between gap-2'>
                  <div>
                    <CardTitle className='text-sm font-medium'>PnL Attribution (Engine × Regime)</CardTitle>
                    <CardDescription>Numeric strings are normalized at the API boundary before rendering.</CardDescription>
                  </div>
                  {walkforward && <ProvenanceBadge source={walkforward.provenance.files.pnl_attribution} />}
                </div>
              </CardHeader>
              <CardContent>
                {attributionByEngineRegime.length > 0 ? (
                  <ResponsiveContainer width='100%' height={260}>
                    <BarChart data={attributionByEngineRegime} layout='vertical' margin={{ top: 0, right: 24, left: 100, bottom: 0 }}>
                      <CartesianGrid strokeDasharray='3 3' className='stroke-muted' horizontal={false} />
                      <XAxis type='number' tick={{ fontSize: 10 }} unit='%' />
                      <YAxis dataKey='name' type='category' tick={{ fontSize: 10 }} width={100} />
                      <Tooltip formatter={(value: number) => `${value}%`} />
                      <Bar dataKey='pnl' fill='#22c55e' radius={[0, 2, 2, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <DashboardEmptyState
                    title='No attribution data available'
                    description='The current run did not produce engine-by-regime attribution rows.'
                  />
                )}
              </CardContent>
            </Card>

            <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
              <Card>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>PnL by Engine</CardTitle>
                </CardHeader>
                <CardContent>
                  {attributionByEngine.length > 0 ? (
                    <ResponsiveContainer width='100%' height={180}>
                      <BarChart data={attributionByEngine} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                        <XAxis dataKey='name' tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 10 }} unit='%' />
                        <Tooltip formatter={(value: number) => `${value}%`} />
                        <Bar dataKey='pnl' fill='#22c55e' radius={[3, 3, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <DashboardEmptyState title='No engine attribution' description='No by-engine attribution rows are available.' />
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>PnL by Regime</CardTitle>
                </CardHeader>
                <CardContent>
                  {attributionByRegime.length > 0 ? (
                    <ResponsiveContainer width='100%' height={180}>
                      <BarChart data={attributionByRegime} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                        <XAxis dataKey='name' tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 10 }} unit='%' />
                        <Tooltip formatter={(value: number) => `${value}%`} />
                        <Bar dataKey='pnl' radius={[3, 3, 0, 0]}>
                          {attributionByRegime.map((row) => (
                            <Cell
                              key={row.name}
                              fill={row.name === 'TREND' ? '#22c55e' : row.name === 'CHOP' ? '#eab308' : '#ef4444'}
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <DashboardEmptyState title='No regime attribution' description='No by-regime attribution rows are available.' />
                  )}
                </CardContent>
              </Card>
            </div>
          </>
        )}

        {!error && section === 'proof' && (
          <>
            <Card>
              <CardHeader className='pb-2'>
                <CardTitle className='text-sm font-medium'>Proof Checks</CardTitle>
                <CardDescription>
                  Promotion-gate checks for regime attribution, risk-off behavior, and engine balance.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {walkforward?.proof_checks ? (
                  <div className='grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3'>
                    {Object.entries(walkforward.proof_checks.checks).map(([name, check]) => (
                      <div
                        key={name}
                        className={`flex items-start gap-2 rounded-md border p-3 ${check.pass ? 'border-green-500/20 bg-green-500/5' : 'border-red-500/20 bg-red-500/5'}`}
                      >
                        {check.pass ? (
                          <IconCheck className='mt-0.5 h-4 w-4 shrink-0 text-green-500' />
                        ) : (
                          <IconX className='mt-0.5 h-4 w-4 shrink-0 text-red-500' />
                        )}
                        <div>
                          <p className='text-xs font-medium'>{name.replace(/_/g, ' ')}</p>
                          <p className='text-muted-foreground text-xs'>
                            value: {check.value ?? '—'}
                            {check.threshold !== null ? ` / threshold ${check.threshold}` : ''}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <DashboardEmptyState
                    title='No proof checks available'
                    description='The current run does not include proof-check output.'
                  />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className='pb-2'>
                <CardTitle className='text-sm font-medium'>Risk Events</CardTitle>
                <CardDescription>Events carried forward from the walk-forward/risk pipeline.</CardDescription>
              </CardHeader>
              <CardContent>
                {(walkforward?.risk_events.length ?? 0) > 0 ? (
                  <div className='space-y-2'>
                    {walkforward?.risk_events.slice(0, 10).map((event, index) => (
                      <div key={`${event.timestamp}-${index}`} className='rounded-md border p-3 text-sm'>
                        <div className='flex items-center justify-between gap-2'>
                          <span className='font-medium'>{event.event_type.replace(/_/g, ' ')}</span>
                          <span className='text-muted-foreground text-xs'>{event.timestamp}</span>
                        </div>
                        <p className='text-muted-foreground text-xs'>{event.message}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <DashboardEmptyState
                    title='No risk events available'
                    description='No risk-events artifact is available for the current walk-forward snapshot.'
                  />
                )}
              </CardContent>
            </Card>
          </>
        )}

        {!error && section === 'model' && (
          <>
            <Card>
              <CardHeader className='pb-2'>
                <div className='flex items-center justify-between gap-2'>
                  <div>
                    <CardTitle className='text-sm font-medium'>Trend Model Metadata</CardTitle>
                    <CardDescription>Model version, calibration, and training context.</CardDescription>
                  </div>
                  {analysis && <ProvenanceBadge source={analysis.provenance.files.trend_model_meta} />}
                </div>
              </CardHeader>
              <CardContent>
                {analysis?.trend_model_meta ? (
                  <div className='grid grid-cols-2 gap-x-8 gap-y-2 sm:grid-cols-3 lg:grid-cols-5'>
                    <div>
                      <p className='text-muted-foreground text-xs'>Model Version</p>
                      <p className='font-mono text-sm font-semibold'>{analysis.trend_model_meta.model_version}</p>
                    </div>
                    <div>
                      <p className='text-muted-foreground text-xs'>Training Window</p>
                      <p className='font-mono text-sm'>{analysis.trend_model_meta.training_window_days}d</p>
                    </div>
                    <div>
                      <p className='text-muted-foreground text-xs'>Last Retrain</p>
                      <p className='font-mono text-sm'>{analysis.trend_model_meta.last_retrain_time.slice(0, 10)}</p>
                    </div>
                    <div>
                      <p className='text-muted-foreground text-xs'>Calibration Score</p>
                      <p className='font-mono text-sm font-semibold'>
                        {analysis.trend_model_meta.calibration_score !== null
                          ? analysis.trend_model_meta.calibration_score.toFixed(2)
                          : '—'}
                      </p>
                    </div>
                    <div>
                      <p className='text-muted-foreground text-xs'>Schema Hash</p>
                      <p className='font-mono text-xs text-muted-foreground'>
                        {analysis.trend_model_meta.feature_schema_hash.slice(0, 8)}...
                      </p>
                    </div>
                  </div>
                ) : (
                  <DashboardEmptyState
                    title='No model metadata available'
                    description='The current run did not emit trend_model_meta.json, so version and calibration details are unavailable.'
                  />
                )}
              </CardContent>
            </Card>

            <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
              <Card>
                <CardHeader className='pb-2'>
                  <div className='flex items-center justify-between gap-2'>
                    <div>
                      <CardTitle className='text-sm font-medium'>SHAP Feature Importance</CardTitle>
                      <CardDescription>Mean absolute SHAP values from trade analysis.</CardDescription>
                    </div>
                    {analysis && <ProvenanceBadge source={analysis.provenance.files.analysis} />}
                  </div>
                </CardHeader>
                <CardContent>
                  {(analysis?.analysis?.feature_importance.length ?? 0) > 0 ? (
                    <ResponsiveContainer width='100%' height={220}>
                      <BarChart
                        data={analysis?.analysis?.feature_importance.map((feature) => ({
                          name: feature.feature,
                          shap: +feature.mean_abs_shap.toFixed(4)
                        }))}
                        layout='vertical'
                        margin={{ top: 0, right: 24, left: 90, bottom: 0 }}
                      >
                        <CartesianGrid strokeDasharray='3 3' className='stroke-muted' horizontal={false} />
                        <XAxis type='number' tick={{ fontSize: 10 }} />
                        <YAxis dataKey='name' type='category' tick={{ fontSize: 10 }} width={90} />
                        <Tooltip />
                        <Bar dataKey='shap' fill='#22c55e' radius={[0, 3, 3, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <DashboardEmptyState
                      title='No feature-importance data'
                      description='trade_analysis.json does not contain SHAP feature importance for this run.'
                    />
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className='pb-2'>
                  <CardTitle className='text-sm font-medium'>Confidence vs Win Rate</CardTitle>
                  <CardDescription>Confidence buckets from the trade-analysis artifact.</CardDescription>
                </CardHeader>
                <CardContent>
                  {confidenceScatter.length > 0 ? (
                    <ResponsiveContainer width='100%' height={220}>
                      <ScatterChart margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray='3 3' className='stroke-muted' />
                        <XAxis type='number' dataKey='confidence' tick={{ fontSize: 10 }} name='Confidence' />
                        <YAxis type='number' dataKey='win_rate' tick={{ fontSize: 10 }} unit='%' name='Win Rate' />
                        <Tooltip cursor={{ strokeDasharray: '3 3' }} />
                        <Scatter data={confidenceScatter} fill='#06b6d4' />
                      </ScatterChart>
                    </ResponsiveContainer>
                  ) : (
                    <DashboardEmptyState
                      title='No confidence buckets available'
                      description='trade_analysis.json does not include confidence bucket outputs for this run.'
                    />
                  )}
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader className='pb-2'>
                <CardTitle className='text-sm font-medium'>Signal Sample</CardTitle>
                <CardDescription>Recent normalized signals available to the UI.</CardDescription>
              </CardHeader>
              <CardContent>
                {(analysis?.signals_sample.length ?? 0) > 0 ? (
                  <div className='overflow-auto'>
                    <table className='w-full text-sm'>
                      <thead>
                        <tr className='text-muted-foreground border-b text-xs'>
                          <th className='pb-2 text-left font-medium'>Time</th>
                          <th className='pb-2 text-left font-medium'>Symbol</th>
                          <th className='pb-2 text-left font-medium'>Direction</th>
                          <th className='pb-2 text-right font-medium'>Confidence</th>
                          <th className='pb-2 text-left font-medium'>Regime</th>
                        </tr>
                      </thead>
                      <tbody>
                        {analysis?.signals_sample.slice(0, 8).map((signal) => (
                          <tr key={`${signal.timestamp}-${signal.symbol}-${signal.direction}`} className='border-b'>
                            <td className='py-2 text-xs'>{signal.timestamp}</td>
                            <td className='py-2 font-mono text-xs'>{signal.symbol}</td>
                            <td className='py-2 text-xs capitalize'>{signal.direction}</td>
                            <td className='py-2 text-right font-mono text-xs'>
                              {(signal.confidence * 100).toFixed(1)}%
                            </td>
                            <td className='py-2 text-xs'>{signal.regime_label}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <DashboardEmptyState
                    title='No signal sample available'
                    description='The current artifact set does not include normalized signal samples.'
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

export default function WalkforwardPage() {
  return (
    <Suspense fallback={<PageContainer><div className='flex flex-1 flex-col gap-4'><Card><CardHeader><CardTitle className='text-sm font-medium'>Loading walk-forward research</CardTitle><CardDescription>Preparing current session analysis.</CardDescription></CardHeader></Card></div></PageContainer>}>
      <WalkforwardPageContent />
    </Suspense>
  );
}
