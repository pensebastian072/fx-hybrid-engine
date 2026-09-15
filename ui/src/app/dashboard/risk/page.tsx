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
import { fetchWalkforwardData } from '@/lib/artifacts';
import type { WalkforwardResponse } from '@/lib/fx-types';
import {
  IconAlertTriangle,
  IconCheck,
  IconRefresh,
  IconShield,
  IconX
} from '@tabler/icons-react';
import { format } from 'date-fns';

const BREAKER_LABELS: Record<string, string> = {
  daily_loss: 'Daily Loss Limit',
  weekly_loss: 'Weekly Loss Limit',
  vol_spike_throttle: 'Vol Spike Throttle',
  reject_spike_throttle: 'Reject Spike Throttle',
  stale_data: 'Stale Data Monitor',
  reconciliation_mismatch: 'Recon Mismatch'
};

const ACTION_COLOR: Record<string, string> = {
  close_only: 'text-red-400',
  flatten: 'text-red-500',
  size_reduced_50pct: 'text-orange-400',
  signal_pause_5min: 'text-yellow-400',
  audit: 'text-blue-400'
};

export default function RiskPage() {
  const [data, setData] = useState<WalkforwardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchWalkforwardData());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const proof = data?.proof_checks;
  const promotion = data?.promotion_decision;
  const opsSummary = promotion?.ops_summary as Record<string, unknown> | undefined;
  const riskEvents = data?.risk_events ?? [];
  const incidents = promotion?.incident_counts ?? {};
  const checks = Object.entries(proof?.checks ?? {});
  const passedChecks = checks.filter(([, check]) => check.pass).length;

  return (
    <PageContainer>
      <div className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>Risk &amp; Guardrails</h2>
            <p className='text-muted-foreground text-sm'>
              Proof checks, incidents, ladder state, and risk-event audit trail.
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
            title='Risk data unavailable'
            description={error}
            action={
              <Button size='sm' variant='outline' onClick={load}>
                Retry
              </Button>
            }
          />
        )}

        {!error && proof && (
          <div
            className={`flex items-center gap-3 rounded-lg border p-4 ${proof.pass ? 'border-green-500/30 bg-green-500/5' : 'border-red-500/30 bg-red-500/5'}`}
          >
            {proof.pass ? (
              <IconCheck className='h-5 w-5 text-green-500' />
            ) : (
              <IconX className='h-5 w-5 text-red-500' />
            )}
            <div>
              <p className='font-semibold'>
                {proof.pass ? 'All proof checks passed' : 'Proof checks failed'}
              </p>
              <p className='text-muted-foreground text-sm'>
                {passedChecks}/{checks.length} checks passing
              </p>
            </div>
          </div>
        )}

        {!error && (
          <div className='grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6'>
            {Object.entries(BREAKER_LABELS).map(([key, label]) => {
              const count = (incidents[key] ?? incidents[key.replace(/_/g, '')] ?? 0) as number;
              const triggered = count > 0;
              return (
                <Card key={key} className={triggered ? 'border-red-500/30 bg-red-500/5' : 'border-green-500/20 bg-green-500/5'}>
                  <CardHeader className='pb-1 pt-3'>
                    <CardDescription className='text-xs'>{label}</CardDescription>
                    <div className='flex items-center gap-2'>
                      {triggered ? (
                        <IconX className='h-4 w-4 text-red-500' />
                      ) : (
                        <IconShield className='h-4 w-4 text-green-500' />
                      )}
                      <CardTitle className={`text-lg font-bold ${triggered ? 'text-red-500' : 'text-green-500'}`}>
                        {triggered ? `${count} hit` : 'OK'}
                      </CardTitle>
                    </div>
                  </CardHeader>
                </Card>
              );
            })}
          </div>
        )}

        {promotion && (
          <div className='grid grid-cols-1 gap-3 sm:grid-cols-3'>
            <Card>
              <CardHeader className='pb-1 pt-3'>
                <CardDescription className='text-xs'>Current Stage</CardDescription>
                <p className='font-mono text-lg font-bold'>{promotion.ladder.current_stage}</p>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className='pb-1 pt-3'>
                <CardDescription className='text-xs'>Ladder Action</CardDescription>
                <p className={`text-lg font-bold capitalize ${promotion.ladder.action === 'promote' ? 'text-green-500' : promotion.ladder.action === 'hold' ? 'text-yellow-500' : 'text-red-500'}`}>
                  {promotion.ladder.action}
                </p>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className='pb-1 pt-3'>
                <CardDescription className='text-xs'>Next Stage</CardDescription>
                <p className='font-mono text-lg font-bold'>{promotion.ladder.next_stage}</p>
              </CardHeader>
            </Card>
          </div>
        )}

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Proof Check Gates</CardTitle>
            <CardDescription>Detailed proof-gate readout from the walk-forward promotion check.</CardDescription>
          </CardHeader>
          <CardContent>
            {checks.length > 0 ? (
              <div className='grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3'>
                {checks.map(([name, check]) => (
                  <div
                    key={name}
                    className={`flex items-start gap-2 rounded-md border p-3 ${check.pass ? 'border-green-500/20 bg-green-500/5' : 'border-red-500/20 bg-red-500/5'}`}
                  >
                    {check.pass ? (
                      <IconCheck className='mt-0.5 h-4 w-4 shrink-0 text-green-500' />
                    ) : (
                      <IconX className='mt-0.5 h-4 w-4 shrink-0 text-red-500' />
                    )}
                    <div className='min-w-0 flex-1'>
                      <p className='truncate text-xs font-medium'>{name.replace(/_/g, ' ')}</p>
                      <p className='text-muted-foreground text-xs'>
                        value: {check.value ?? '—'}
                        {check.threshold !== null ? ` / threshold: ${check.threshold}` : ''}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <DashboardEmptyState
                title='No proof check data'
                description='The current artifact set does not include proof-check outputs.'
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='pb-2'>
            <div className='flex items-center justify-between gap-2'>
              <div>
                <CardTitle className='text-sm font-medium'>Risk Events Feed</CardTitle>
                <CardDescription>Breaker triggers, throttles, and data incidents.</CardDescription>
              </div>
              {data && <ProvenanceBadge source={data.provenance.files.risk_events} />}
            </div>
          </CardHeader>
          <CardContent>
            {riskEvents.length > 0 ? (
              <div className='overflow-auto'>
                <table className='w-full text-xs'>
                  <thead>
                    <tr className='text-muted-foreground border-b'>
                      <th className='pb-2 text-left font-medium'>Time</th>
                      <th className='pb-2 text-left font-medium'>Reason</th>
                      <th className='pb-2 text-left font-medium'>Action</th>
                      <th className='pb-2 text-left font-medium'>Symbols</th>
                      <th className='pb-2 text-left font-medium'>Message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {riskEvents.map((event, index) => (
                      <tr key={`${event.timestamp}-${index}`} className='border-b last:border-0'>
                        <td className='text-muted-foreground py-2 pr-4 font-mono'>
                          {format(new Date(event.timestamp), 'MM-dd HH:mm')}
                        </td>
                        <td className='py-2 pr-4'>
                          <span className='rounded bg-muted px-1.5 py-0.5 font-mono'>
                            {event.reason_code ?? '—'}
                          </span>
                        </td>
                        <td className={`py-2 pr-4 font-medium ${ACTION_COLOR[event.action ?? ''] ?? 'text-muted-foreground'}`}>
                          {event.action ?? '—'}
                        </td>
                        <td className='py-2 pr-4'>
                          {(event.symbols ?? []).map((symbol, symbolIndex) => (
                            <span key={`${symbol}-${symbolIndex}`} className='mr-1 rounded bg-muted px-1 py-0.5 font-mono text-xs'>
                              {symbol}
                            </span>
                          ))}
                        </td>
                        <td className='text-muted-foreground py-2'>{event.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <DashboardEmptyState
                title='No risk events emitted'
                description='No risk-event artifact was emitted for the current run, and no fallback events are available.'
              />
            )}
          </CardContent>
        </Card>

        {promotion?.incident_counts && (
          <Card>
            <CardHeader className='pb-2'>
              <CardTitle className='text-sm font-medium'>Incident Counts</CardTitle>
              <CardDescription>Paper-session incident totals used by the promotion gate.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className='flex flex-wrap gap-4'>
                {Object.entries(promotion.incident_counts).map(([key, value]) => (
                  <div key={key} className='flex flex-col items-center gap-1'>
                    <p className={`text-2xl font-bold tabular-nums ${value > 0 ? 'text-red-500' : 'text-green-500'}`}>
                      {value}
                    </p>
                    <p className='text-muted-foreground text-xs'>{key.replace(/_/g, ' ')}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {opsSummary && Object.keys(opsSummary).length > 0 && (
          <Card>
            <CardHeader className='pb-2'>
              <CardTitle className='text-sm font-medium'>Ops Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <div className='grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-3'>
                {Object.entries(opsSummary)
                  .filter(([, value]) => typeof value === 'number' || typeof value === 'string')
                  .map(([key, value]) => (
                    <div key={key} className='flex items-center justify-between'>
                      <span className='text-muted-foreground text-xs'>{key.replace(/_/g, ' ')}</span>
                      <span className='font-mono text-xs'>
                        {typeof value === 'number' ? value.toFixed(4) : String(value)}
                      </span>
                    </div>
                  ))}
              </div>
            </CardContent>
          </Card>
        )}

        {promotion && promotion.failed_reasons.length > 0 && (
          <Card className='border-red-500/20'>
            <CardHeader className='pb-2'>
              <CardTitle className='flex items-center gap-2 text-sm font-medium'>
                <IconAlertTriangle className='h-4 w-4 text-red-500' />
                Failed Gates
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className='flex flex-wrap gap-2'>
                {promotion.failed_reasons.map((reason) => (
                  <Badge key={reason} variant='destructive'>
                    {reason.replace(/_/g, ' ')}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </PageContainer>
  );
}
