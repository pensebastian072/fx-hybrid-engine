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
import { fetchPaperOps } from '@/lib/artifacts';
import type { PaperOpsState } from '@/lib/fx-types';
import {
  IconAlertTriangle,
  IconCheck,
  IconDownload,
  IconRefresh
} from '@tabler/icons-react';
import { format } from 'date-fns';

function CopyBadge({ value }: { value: string }) {
  return (
    <span
      className='bg-muted cursor-pointer rounded px-1.5 py-0.5 font-mono text-xs hover:opacity-80'
      onClick={() => navigator.clipboard.writeText(value).catch(() => {})}
      title='Click to copy'
    >
      {value}
    </span>
  );
}

export default function PaperOpsPage() {
  const [data, setData] = useState<PaperOpsState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchPaperOps());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <PageContainer>
        <div className='flex h-64 items-center justify-center'>
          <p className='text-muted-foreground text-sm'>Loading paper ops…</p>
        </div>
      </PageContainer>
    );
  }

  if (error || !data) {
    return (
      <PageContainer>
        <DashboardEmptyState
          title='Paper ops unavailable'
          description={error ?? 'No paper ops data found.'}
          action={
            <Button variant='outline' size='sm' onClick={load}>
              Retry
            </Button>
          }
        />
      </PageContainer>
    );
  }

  const manifest = data.run_manifest;
  const hasIssues =
    data.stale_data_count > 0 ||
    data.missing_bars_count > 0 ||
    data.reject_rate > 0.1;
  const isDemo = data.provenance.overall === 'mock';
  const isHistoricalRun = data.provenance.overall === 'run_history';
  const strategyNotStarted = manifest.strategy_status === 'not_started';
  const simulatedPaperData = manifest.simulated_market_data === true;
  const localPaperRouting = manifest.broker_order_routing === 'local_paper_only';
  const brokerContext = data.broker_context;
  const noTradeSummary = data.no_trade_summary;
  const strategySummary = data.strategy_summary;
  const brokerHealthy = brokerContext?.available === true;

  return (
    <PageContainer>
      <div className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>Paper Ops</h2>
            <p className='text-muted-foreground text-sm'>
              Paper-session health and reproducibility details.
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <ProvenanceBadge source={data.provenance.overall} />
            <Button size='sm' variant='outline' onClick={load} disabled={loading}>
              <IconRefresh className='mr-1 h-3 w-3' />
              Refresh
            </Button>
          </div>
        </div>

        {isDemo && (
          <Card className='border-yellow-500/30 bg-yellow-500/5'>
            <CardContent className='flex items-center gap-2 pt-6 text-sm'>
              <IconAlertTriangle className='h-4 w-4 text-yellow-500' />
              Paper Ops is currently powered by demo fallback data because no live `paper_ops.json` artifact was found.
            </CardContent>
          </Card>
        )}

        {isHistoricalRun && (
          <Card className='border-sky-500/30 bg-sky-500/5'>
            <CardContent className='flex items-center gap-2 pt-6 text-sm'>
              <IconCheck className='h-4 w-4 text-sky-400' />
              You are viewing an archived paper snapshot from `outputs/paper`, not the moving `latest_run` session projection.
            </CardContent>
          </Card>
        )}

        {!isDemo && strategyNotStarted && (
          <Card className='border-yellow-500/30 bg-yellow-500/5'>
            <CardContent className='flex items-center gap-2 pt-6 text-sm'>
              <IconAlertTriangle className='h-4 w-4 text-yellow-500' />
              No real paper session snapshot has been normalized yet. This page is now showing the latest known paper status instead of mock data.
            </CardContent>
          </Card>
        )}

        {!isDemo && simulatedPaperData && (
          <Card className='border-blue-500/30 bg-blue-500/5'>
            <CardContent className='flex items-center gap-2 pt-6 text-sm'>
              <IconAlertTriangle className='h-4 w-4 text-blue-400' />
              Current paper telemetry uses `lean_history` synthetic bars, so it is useful for automation checks but not real market execution.
            </CardContent>
          </Card>
        )}

        {!isDemo && localPaperRouting && (
          <Card className='border-blue-500/30 bg-blue-500/5'>
            <CardContent className='flex items-center gap-2 pt-6 text-sm'>
              <IconAlertTriangle className='h-4 w-4 text-blue-400' />
              Strategy fills are still local paper-only. The Tastytrade rail is connected for account state, but order routing is not live yet.
            </CardContent>
          </Card>
        )}

        <div className='flex items-center gap-2'>
          <Badge variant={hasIssues ? 'destructive' : 'default'}>
            {hasIssues ? (
              <>
                <IconAlertTriangle className='mr-1 h-3 w-3' />
                Issues detected
              </>
            ) : (
              <>
                <IconCheck className='mr-1 h-3 w-3' />
                Healthy
              </>
            )}
          </Badge>
        </div>

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Session Manifest</CardTitle>
            <CardDescription>Audit and reproducibility metadata.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className='grid grid-cols-1 gap-x-8 gap-y-2.5 text-sm sm:grid-cols-2 lg:grid-cols-3'>
              <div className='flex flex-col gap-0.5'>
                <span className='text-muted-foreground text-xs'>Session ID</span>
                <CopyBadge value={manifest.run_id} />
              </div>
              <div className='flex flex-col gap-0.5'>
                <span className='text-muted-foreground text-xs'>Git Commit</span>
                <CopyBadge value={manifest.git_commit} />
              </div>
              <div className='flex flex-col gap-0.5'>
                <span className='text-muted-foreground text-xs'>Config Hash</span>
                <CopyBadge value={manifest.config_hash.replace('sha256:', '')} />
              </div>
              <div className='flex flex-col gap-0.5'>
                <span className='text-muted-foreground text-xs'>Schema Version</span>
                <span className='font-mono text-xs'>{manifest.schema_version}</span>
              </div>
              <div className='flex flex-col gap-0.5'>
                <span className='text-muted-foreground text-xs'>Created At (UTC)</span>
                <span className='font-mono text-xs'>
                  {format(new Date(manifest.created_at_utc), 'yyyy-MM-dd HH:mm:ss')}
                </span>
              </div>
              <div className='flex flex-col gap-0.5'>
                <span className='text-muted-foreground text-xs'>Seed</span>
                <span className='font-mono text-xs'>{manifest.seed}</span>
              </div>
               <div className='flex flex-col gap-0.5'>
                 <span className='text-muted-foreground text-xs'>Data Profile</span>
                 <span className='font-mono text-xs'>{manifest.data_profile}</span>
               </div>
               <div className='flex flex-col gap-0.5'>
                 <span className='text-muted-foreground text-xs'>Execution Rail</span>
                 <span className='font-mono text-xs'>
                   {manifest.live_broker ?? 'unknown'} / {manifest.live_rail ?? 'unknown'}
                 </span>
               </div>
               <div className='flex flex-col gap-0.5'>
                 <span className='text-muted-foreground text-xs'>Routing Mode</span>
                 <span className='font-mono text-xs'>{manifest.broker_order_routing ?? 'unknown'}</span>
               </div>
               <div className='flex flex-col gap-0.5'>
                 <span className='text-muted-foreground text-xs'>Pipeline Version</span>
                 <span className='font-mono text-xs'>{manifest.pipeline_version}</span>
               </div>
              <div className='flex flex-col gap-0.5'>
                <span className='text-muted-foreground text-xs'>Toggles</span>
                <div className='flex flex-wrap gap-1'>
                  <Badge variant={manifest.precompute_enabled ? 'default' : 'outline'} className='text-xs'>
                    precompute {manifest.precompute_enabled ? 'on' : 'off'}
                  </Badge>
                  <Badge variant={manifest.mode_reuse_enabled ? 'default' : 'outline'} className='text-xs'>
                    mode-reuse {manifest.mode_reuse_enabled ? 'on' : 'off'}
                  </Badge>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className='grid grid-cols-2 gap-3 sm:grid-cols-4'>
          {[
            {
              label: 'Stale Data Events',
              value: data.stale_data_count,
              bad: data.stale_data_count > 0
            },
            {
              label: 'Missing Bars',
              value: data.missing_bars_count,
              bad: data.missing_bars_count > 0
            },
            {
              label: 'Orders / Hour',
              value: data.orders_per_hour.toFixed(1),
              bad: false
            },
            {
              label: 'Reject Rate',
              value: `${(data.reject_rate * 100).toFixed(1)}%`,
              bad: data.reject_rate > 0.1
            }
          ].map((item) => (
            <Card key={item.label}>
              <CardHeader className='pb-1 pt-3'>
                <CardDescription className='text-xs'>{item.label}</CardDescription>
                <p className={`text-2xl font-bold tabular-nums ${item.bad ? 'text-red-500' : 'text-foreground'}`}>
                  {item.value}
                </p>
              </CardHeader>
            </Card>
          ))}
        </div>

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Session Status</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge
              variant={
                data.objectstore_status === 'connected' || data.objectstore_status === 'running'
                  ? 'default'
                  : data.objectstore_status === 'not_configured' ||
                      data.objectstore_status === 'stopped'
                    ? 'outline'
                    : 'destructive'
              }
              className='text-sm'
            >
              {data.objectstore_status}
            </Badge>
          </CardContent>
        </Card>

        <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
          <Card>
            <CardHeader className='pb-2'>
              <div className='flex items-center justify-between gap-2'>
                <div>
                  <CardTitle className='text-sm font-medium'>Broker Context</CardTitle>
                  <CardDescription>Account-state visibility for this local paper session.</CardDescription>
                </div>
                <Badge variant={brokerHealthy ? 'default' : 'outline'}>
                  {brokerHealthy ? 'Connected' : 'Unavailable'}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className='space-y-3 text-sm'>
              {brokerContext ? (
                <>
                  <div className='grid grid-cols-2 gap-x-4 gap-y-2 text-xs'>
                    <span className='text-muted-foreground'>Provider</span>
                    <span className='text-right font-mono'>{brokerContext.provider ?? 'tastytrade'}</span>
                    <span className='text-muted-foreground'>Connection</span>
                    <span className='text-right font-mono'>{brokerContext.connection_status}</span>
                    <span className='text-muted-foreground'>Account</span>
                    <span className='text-right font-mono'>{brokerContext.account_number ?? '—'}</span>
                    <span className='text-muted-foreground'>Positions</span>
                    <span className='text-right font-mono'>{brokerContext.positions_count ?? 0}</span>
                    <span className='text-muted-foreground'>Open Orders</span>
                    <span className='text-right font-mono'>{brokerContext.open_orders_count ?? 0}</span>
                    <span className='text-muted-foreground'>Mapped Symbols</span>
                    <span className='text-right font-mono'>{brokerContext.symbol_map_ready_count ?? 0}</span>
                  </div>
                  {brokerContext.symbol_map_missing && brokerContext.symbol_map_missing.length > 0 && (
                    <div className='space-y-1'>
                      <p className='text-muted-foreground text-xs'>Missing symbol-map entries</p>
                      <div className='flex flex-wrap gap-1'>
                        {brokerContext.symbol_map_missing.map((symbol, symbolIndex) => (
                          <Badge key={`${symbol}-${symbolIndex}`} variant='outline' className='text-[10px]'>
                            {symbol}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  {brokerContext.error && (
                    <p className='text-muted-foreground text-xs'>{brokerContext.error}</p>
                  )}
                </>
              ) : (
                <DashboardEmptyState
                  title='Broker context unavailable'
                  description='The current session artifact set did not emit broker context telemetry.'
                />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className='pb-2'>
              <CardTitle className='text-sm font-medium'>No-Trade Diagnostics</CardTitle>
              <CardDescription>
                Why the current session did or did not produce fills.
              </CardDescription>
            </CardHeader>
            <CardContent className='space-y-3'>
              {noTradeSummary ? (
                <>
                  <div className='grid grid-cols-2 gap-3 sm:grid-cols-3'>
                    {[
                      ['Signals', noTradeSummary.signals_emitted ?? 0],
                      ['Fills', noTradeSummary.fills_emitted ?? 0],
                      ['Closed Trades', noTradeSummary.closed_trades ?? 0],
                      ['Observed Pairs', noTradeSummary.observed_pair_count ?? 0],
                      ['Tradable Pairs', noTradeSummary.tradable_pair_count ?? 0],
                      ['Confidence Misses', noTradeSummary.trend_confidence_misses ?? 0]
                    ].map(([label, value]) => (
                      <div key={String(label)} className='rounded-md border p-3'>
                        <p className='text-muted-foreground text-[11px]'>{label}</p>
                        <p className='text-lg font-semibold tabular-nums'>{value}</p>
                      </div>
                    ))}
                  </div>
                  {noTradeSummary.pair_reason_counts &&
                    Object.keys(noTradeSummary.pair_reason_counts).length > 0 && (
                      <div className='space-y-2'>
                        <p className='text-muted-foreground text-xs'>Pair no-trade reasons</p>
                        <div className='flex flex-wrap gap-2'>
                          {Object.entries(noTradeSummary.pair_reason_counts)
                            .sort((left, right) => right[1] - left[1])
                            .map(([reason, count]) => (
                              <Badge key={reason} variant='outline' className='text-[10px]'>
                                {reason}: {count}
                              </Badge>
                            ))}
                        </div>
                      </div>
                    )}
                </>
              ) : (
                <DashboardEmptyState
                  title='No-trade telemetry unavailable'
                  description='The current session artifact set did not emit no-trade summary counters.'
                />
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Strategy Snapshot</CardTitle>
            <CardDescription>Current paper-strategy output counters and status.</CardDescription>
          </CardHeader>
          <CardContent>
            {strategySummary ? (
              <div className='grid grid-cols-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4'>
                <div className='flex flex-col gap-0.5'>
                  <span className='text-muted-foreground text-xs'>Status</span>
                  <span className='font-mono text-xs'>{strategySummary.status ?? '—'}</span>
                </div>
                <div className='flex flex-col gap-0.5'>
                  <span className='text-muted-foreground text-xs'>Last Regime</span>
                  <span className='font-mono text-xs'>{strategySummary.last_regime ?? '—'}</span>
                </div>
                <div className='flex flex-col gap-0.5'>
                  <span className='text-muted-foreground text-xs'>Bars Written</span>
                  <span className='font-mono text-xs'>{strategySummary.bars_written ?? 0}</span>
                </div>
                <div className='flex flex-col gap-0.5'>
                  <span className='text-muted-foreground text-xs'>Active Positions</span>
                  <span className='font-mono text-xs'>{strategySummary.active_position_count ?? 0}</span>
                </div>
                <div className='flex flex-col gap-0.5'>
                  <span className='text-muted-foreground text-xs'>Signals</span>
                  <span className='font-mono text-xs'>{strategySummary.signals_emitted ?? 0}</span>
                </div>
                <div className='flex flex-col gap-0.5'>
                  <span className='text-muted-foreground text-xs'>Fills</span>
                  <span className='font-mono text-xs'>{strategySummary.fills_emitted ?? 0}</span>
                </div>
                <div className='flex flex-col gap-0.5'>
                  <span className='text-muted-foreground text-xs'>Closed Trades</span>
                  <span className='font-mono text-xs'>{strategySummary.closed_trades ?? 0}</span>
                </div>
                <div className='flex flex-col gap-0.5'>
                  <span className='text-muted-foreground text-xs'>Contract Ready</span>
                  <span className='font-mono text-xs'>
                    {strategySummary.contract_ready_position_count ?? 0}/
                    {strategySummary.position_plan_count ?? 0}
                  </span>
                </div>
              </div>
            ) : (
              <DashboardEmptyState
                title='Strategy summary unavailable'
                description='The current session artifact set did not emit a detailed paper strategy summary.'
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Last Bar Preview</CardTitle>
            <CardDescription>
              Most recent prices from the paper-session snapshot.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {data.last_bars.length > 0 ? (
              <div className='flex flex-wrap gap-4'>
                {data.last_bars.map((bar, barIndex) => (
                  <div key={`${bar.symbol}-${barIndex}`} className='flex flex-col items-center gap-1'>
                    <span className='text-muted-foreground text-xs'>{bar.symbol}</span>
                    <span className='font-mono text-sm font-bold'>{bar.close.toFixed(5)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <DashboardEmptyState
                title='No bar preview available'
                description='This paper snapshot does not contain recent bar previews.'
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Export Snapshot</CardTitle>
            <CardDescription>Download the current paper ops payload as JSON.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant='outline'
              size='sm'
              className='text-xs'
              onClick={() => {
                const blob = new Blob([JSON.stringify(data, null, 2)], {
                  type: 'application/json'
                });
                const url = URL.createObjectURL(blob);
                const anchor = document.createElement('a');
                anchor.href = url;
                anchor.download = `${manifest.run_id}_paper_ops.json`;
                anchor.click();
                URL.revokeObjectURL(url);
              }}
            >
              <IconDownload className='mr-1 h-3 w-3' />
              Download Paper Snapshot
            </Button>
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
