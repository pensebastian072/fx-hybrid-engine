'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { DashboardEmptyState } from '@/components/dashboard/empty-state';
import {
  IconDeviceFloppy,
  IconLoader2,
  IconPlayerPlay,
  IconRefresh
} from '@tabler/icons-react';

type RunStatus = 'idle' | 'running' | 'success' | 'error';
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';
type ExecutionProfile = 'local_paper' | 'scaffold' | 'qc_push';

interface RunParams {
  executionProfile: ExecutionProfile;
  maxSplits: string;
  paperRunSeconds: string;
  configPath: string;
  skipTraining: string;
  skipWalkforward: string;
  skipPaperSession: string;
}

const RUN_CONFIG_OPTIONS = [
  'config/default.yaml',
  'config/ladder.yaml',
  'config/pairs_policy.yaml'
] as const;

const EXECUTION_PROFILES = [
  {
    id: 'local_paper',
    label: 'Refresh Current Session',
    description: 'Runs the shared local paper strategy path and emits strategy artifacts.'
  },
  {
    id: 'scaffold',
    label: 'Initialize Session Scaffold',
    description: 'Bootstraps session scaffolding only. No strategy cycle is executed.'
  },
  {
    id: 'qc_push',
    label: 'Sync QC Paper Rail',
    description: 'Runs the QuantConnect paper sync without refreshing local strategy artifacts.'
  }
] as const;

const CONFIG_FILES = [
  {
    id: 'default',
    label: 'default.yaml',
    path: 'config/default.yaml',
    description: 'Primary runtime config passed to run_algo.ps1.'
  },
  {
    id: 'pairs_policy',
    label: 'pairs_policy.yaml',
    path: 'config/pairs_policy.yaml',
    description: 'Pairs scan thresholds and overrides.'
  },
  {
    id: 'ladder',
    label: 'ladder.yaml',
    path: 'config/ladder.yaml',
    description: 'Promotion ladder and stage transitions.'
  }
] as const;

type ConfigFileId = (typeof CONFIG_FILES)[number]['id'];

export default function SettingsPage() {
  const [params, setParams] = useState<RunParams>({
    executionProfile: 'local_paper',
    maxSplits: '1',
    paperRunSeconds: '60',
    configPath: 'config/default.yaml',
    skipTraining: 'false',
    skipWalkforward: 'false',
    skipPaperSession: 'false'
  });

  const [status, setStatus] = useState<RunStatus>('idle');
  const [log, setLog] = useState('');
  const [exitCode, setExitCode] = useState<number | null>(null);
  const logRef = useRef<HTMLPreElement>(null);

  const [activeConfig, setActiveConfig] = useState<ConfigFileId>('default');
  const [configContent, setConfigContent] = useState('');
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [saveError, setSaveError] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);

  const activeConfigMeta = CONFIG_FILES.find((file) => file.id === activeConfig)!;

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

  function update(key: keyof RunParams, value: string) {
    setParams((current) => ({ ...current, [key]: value }));
  }

  const runLabel =
    params.executionProfile === 'local_paper'
      ? 'Refresh Current Session'
      : params.executionProfile === 'scaffold'
        ? 'Initialize Session Scaffold'
        : 'Sync QC Paper Rail';

  const selectedProfile = EXECUTION_PROFILES.find(
    (profile) => profile.id === params.executionProfile
  );

  const runAlgo = useCallback(async (overrides?: Partial<RunParams>) => {
    const payload = { ...params, ...overrides };
    const profileLabel =
      EXECUTION_PROFILES.find((profile) => profile.id === payload.executionProfile)?.label ??
      payload.executionProfile;
    setStatus('running');
    setLog(`Starting ${profileLabel}...\n`);
    setExitCode(null);

    try {
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = (await res.json()) as {
        status: string;
        exit_code: number;
        stdout: string;
        stderr: string;
        duration_ms: number;
      };
      const output = [
        data.stdout,
        data.stderr ? `\n--- STDERR ---\n${data.stderr}` : '',
        `\n--- Finished in ${(data.duration_ms / 1000).toFixed(1)}s (exit ${data.exit_code}) ---`
      ]
        .filter(Boolean)
        .join('');

      setLog(output || 'Action completed with no log output.');
      setExitCode(data.exit_code);
      setStatus(data.exit_code === 0 ? 'success' : 'error');
    } catch (error) {
      setLog(`Error: ${error instanceof Error ? error.message : String(error)}`);
      setStatus('error');
    }
  }, [params]);

  const handleRun = useCallback(async () => {
    await runAlgo();
  }, [runAlgo]);

  const loadConfig = useCallback(async (fileId: ConfigFileId) => {
    setConfigLoading(true);
    setConfigError(null);
    setSaveStatus('idle');
    setSaveError('');
    setWarnings([]);

    try {
      const res = await fetch(`/api/config?file=${fileId}`, { cache: 'no-store' });
      if (!res.ok) {
        const payload = (await res.json().catch(() => ({ error: 'Unknown error' }))) as {
          error?: string;
        };
        setConfigContent('');
        setConfigError(payload.error ?? `Failed to load ${fileId}`);
        return;
      }
      setConfigContent(await res.text());
    } catch (error) {
      setConfigContent('');
      setConfigError(error instanceof Error ? error.message : String(error));
    } finally {
      setConfigLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadConfig(activeConfig);
  }, [activeConfig, loadConfig]);

  function validateYaml(content: string): string[] {
    const nextWarnings: string[] = [];
    if (content.includes('\t')) {
      nextWarnings.push('YAML should use spaces instead of tabs.');
    }
    if (content.length > 50000) {
      nextWarnings.push('File is unusually large. Double-check before saving.');
    }
    if (activeConfig === 'pairs_policy' && !content.includes('lookback_bars')) {
      nextWarnings.push('pairs_policy.yaml: lookback_bars not found.');
    }
    if (activeConfig === 'ladder' && !content.includes('stage')) {
      nextWarnings.push('ladder.yaml: no stage definition found.');
    }
    return nextWarnings;
  }

  const handleSave = useCallback(async () => {
    const nextWarnings = validateYaml(configContent);
    setWarnings(nextWarnings);
    setSaveStatus('saving');
    setSaveError('');

    try {
      const res = await fetch(`/api/config?file=${activeConfig}`, {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain' },
        body: configContent
      });

      if (!res.ok) {
        const payload = (await res.json().catch(() => ({ error: 'Save failed' }))) as {
          error?: string;
        };
        setSaveError(payload.error ?? 'Save failed');
        setSaveStatus('error');
        return;
      }

      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2500);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
      setSaveStatus('error');
    }
  }, [activeConfig, configContent]);

  const statusVariant: Record<RunStatus, 'secondary' | 'outline' | 'default' | 'destructive'> = {
    idle: 'secondary',
    running: 'outline',
    success: 'default',
    error: 'destructive'
  };

  return (
    <PageContainer>
      <div className='flex flex-1 flex-col gap-6'>
        <div className='flex items-center justify-between'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>Settings</h2>
            <p className='text-muted-foreground text-sm'>
              Session admin controls and editable config files for the always-current strategy workspace.
            </p>
          </div>
          <Badge variant={statusVariant[status]}>
            {status === 'running'
              ? 'Running...'
              : status.charAt(0).toUpperCase() + status.slice(1)}
          </Badge>
        </div>

        <div className='grid grid-cols-1 gap-6 lg:grid-cols-2'>
          <Card>
            <CardHeader>
              <CardTitle className='text-sm font-medium'>Session Maintenance</CardTitle>
              <CardDescription>
                Manual actions are for maintenance and recovery only. The main dashboard should read one current session.
              </CardDescription>
            </CardHeader>
            <CardContent className='space-y-4'>
              <div className='space-y-1'>
                <Label htmlFor='configPath'>Config Path</Label>
                <select
                  id='configPath'
                  aria-label='Config Path'
                  value={params.configPath}
                  onChange={(event) => update('configPath', event.target.value)}
                  className='border-input bg-background ring-offset-background focus-visible:ring-ring flex h-10 w-full rounded-md border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2'
                >
                  {RUN_CONFIG_OPTIONS.map((configPath) => (
                    <option key={configPath} value={configPath}>
                      {configPath}
                    </option>
                  ))}
                </select>
              </div>
              <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
                <div className='space-y-1'>
                  <Label htmlFor='executionProfile'>Maintenance Action</Label>
                  <select
                    id='executionProfile'
                    aria-label='Maintenance Action'
                    value={params.executionProfile}
                    onChange={(event) =>
                      update('executionProfile', event.target.value as ExecutionProfile)
                    }
                    className='border-input bg-background ring-offset-background focus-visible:ring-ring flex h-10 w-full rounded-md border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2'
                  >
                    {EXECUTION_PROFILES.map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className='space-y-1'>
                  <Label htmlFor='maxSplits'>Max Splits</Label>
                  <Input
                    id='maxSplits'
                    type='number'
                    min={1}
                    max={20}
                    value={params.maxSplits}
                    onChange={(event) => update('maxSplits', event.target.value)}
                  />
                </div>
                <div className='space-y-1'>
                  <Label htmlFor='paperRunSeconds'>Session Refresh Seconds</Label>
                  <Input
                    id='paperRunSeconds'
                    type='number'
                    min={10}
                    max={3600}
                    value={params.paperRunSeconds}
                    onChange={(event) => update('paperRunSeconds', event.target.value)}
                  />
                </div>
              </div>
              <p className='text-muted-foreground text-xs'>
                {selectedProfile?.description}
              </p>
              <div className='space-y-2 pt-2'>
                <p className='text-muted-foreground text-xs font-medium uppercase'>Skip Steps</p>
                {([
                  ['skipTraining', 'Skip Training'],
                  ['skipWalkforward', 'Skip Walk-forward'],
                  ['skipPaperSession', 'Skip Paper Session']
                ] as [keyof RunParams, string][]).map(([key, label]) => (
                  <label key={key} className='flex cursor-pointer items-center gap-2 text-sm'>
                    <input
                      type='checkbox'
                      checked={params[key] === 'true'}
                      onChange={(event) =>
                        update(key, event.target.checked ? 'true' : 'false')
                      }
                      className='h-4 w-4 rounded'
                    />
                    {label}
                  </label>
                ))}
              </div>
              <Button className='w-full' onClick={handleRun} disabled={status === 'running'}>
                {status === 'running' ? (
                  <>
                    <IconLoader2 className='mr-2 h-4 w-4 animate-spin' />
                    Working...
                  </>
                ) : (
                  <>
                    <IconPlayerPlay className='mr-2 h-4 w-4' />
                    {runLabel}
                  </>
                )}
              </Button>
              <div className='grid grid-cols-1 gap-2 sm:grid-cols-2'>
                <Button
                  variant='outline'
                  onClick={() => void runAlgo({ executionProfile: 'scaffold' })}
                  disabled={status === 'running'}
                >
                  Initialize Session Scaffold
                </Button>
                <Button
                  variant='outline'
                  onClick={() => void runAlgo({ executionProfile: 'qc_push' })}
                  disabled={status === 'running'}
                >
                  Sync QC Paper Rail
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className='text-sm font-medium'>Action Log</CardTitle>
              <CardDescription>
                stdout / stderr from the maintenance action runner
                {exitCode !== null && (
                  <span className='ml-2'>
                    Exit code:{' '}
                    <span className={exitCode === 0 ? 'text-green-500' : 'text-red-500'}>
                      {exitCode}
                    </span>
                  </span>
                )}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <pre
                ref={logRef}
                className='bg-muted text-muted-foreground h-80 overflow-auto rounded p-3 text-xs leading-relaxed whitespace-pre-wrap'
              >
                {log || 'Action output will appear here.'}
              </pre>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className='text-sm font-medium'>Config Editor</CardTitle>
            <CardDescription>
              Only live runtime config files are exposed here. Missing files return explicit errors.
            </CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            <div className='flex flex-wrap gap-1 border-b pb-2'>
              {CONFIG_FILES.map((file) => (
                <button
                  key={file.id}
                  onClick={() => setActiveConfig(file.id)}
                  className={
                    'rounded-sm px-3 py-1 text-xs font-mono font-medium transition-colors ' +
                    (activeConfig === file.id
                      ? 'bg-muted text-foreground'
                      : 'text-muted-foreground hover:text-foreground')
                  }
                >
                  {file.label}
                </button>
              ))}
              <button
                onClick={() => void loadConfig(activeConfig)}
                className='text-muted-foreground hover:text-foreground ml-auto p-1'
                title='Reload from disk'
              >
                <IconRefresh className='h-3 w-3' />
              </button>
            </div>

            <div className='flex flex-wrap items-center gap-2 text-xs'>
              <Badge variant='outline'>{activeConfigMeta.path}</Badge>
              <span className='text-muted-foreground'>{activeConfigMeta.description}</span>
            </div>

            {warnings.length > 0 && (
              <div className='rounded-md border border-yellow-500/40 bg-yellow-500/10 p-2'>
                {warnings.map((warning) => (
                  <p key={warning} className='text-xs text-yellow-500'>
                    warning: {warning}
                  </p>
                ))}
              </div>
            )}

            {saveStatus === 'error' && (
              <div className='rounded-md border border-red-500/40 bg-red-500/10 p-2'>
                <p className='text-xs text-red-500'>Save failed: {saveError}</p>
              </div>
            )}

            {saveStatus === 'saved' && (
              <div className='rounded-md border border-green-500/40 bg-green-500/10 p-2'>
                <p className='text-xs text-green-500'>Saved successfully.</p>
              </div>
            )}

            {configError ? (
              <DashboardEmptyState
                title='Config file unavailable'
                description={configError}
                action={
                  <Button variant='outline' size='sm' onClick={() => void loadConfig(activeConfig)}>
                    Retry
                  </Button>
                }
              />
            ) : (
              <>
                <textarea
                  className='bg-muted text-foreground h-96 w-full rounded border p-3 font-mono text-xs leading-relaxed focus:outline-none focus:ring-1 focus:ring-blue-500'
                  aria-label={`Config editor for ${activeConfigMeta.label}`}
                  value={configLoading ? 'Loading...' : configContent}
                  onChange={(event) => {
                    setConfigContent(event.target.value);
                    setSaveStatus('idle');
                  }}
                  disabled={configLoading}
                  spellCheck={false}
                />

                <div className='flex items-center justify-between'>
                  <p className='text-muted-foreground text-xs'>
                    {configContent.split('\n').length} lines / {configContent.length} bytes
                  </p>
                  <Button
                    size='sm'
                    onClick={() => void handleSave()}
                    disabled={saveStatus === 'saving' || configLoading || Boolean(configError)}
                  >
                    {saveStatus === 'saving' ? (
                      <>
                        <IconLoader2 className='mr-1 h-3 w-3 animate-spin' />
                        Saving...
                      </>
                    ) : (
                      <>
                        <IconDeviceFloppy className='mr-1 h-3 w-3' />
                        Save
                      </>
                    )}
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
