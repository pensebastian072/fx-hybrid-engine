import type { ArtifactSource, DataProvenance } from '@/lib/fx-types';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';

interface ProvenanceBadgeProps {
  source: ArtifactSource | DataProvenance['overall'];
  className?: string;
}

const SOURCE_META: Record<ArtifactSource | DataProvenance['overall'], { label: string; variant: 'default' | 'secondary' | 'outline' | 'destructive'; className?: string }> = {
  latest_run: { label: 'Latest Artifacts', variant: 'default' },
  run_history: { label: 'Historical Run', variant: 'secondary' },
  mock: { label: 'Demo Fallback', variant: 'outline', className: 'text-yellow-500 border-yellow-500/40' },
  mixed: { label: 'Mixed Data', variant: 'secondary' },
  missing: { label: 'Unavailable', variant: 'destructive' }
};

export function ProvenanceBadge({ source, className }: ProvenanceBadgeProps) {
  const meta = SOURCE_META[source];
  return (
    <Badge variant={meta.variant} className={cn('text-xs', meta.className, className)}>
      {meta.label}
    </Badge>
  );
}
