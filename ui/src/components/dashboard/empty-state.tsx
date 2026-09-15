import type { ReactNode } from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { cn } from '@/lib/utils';

interface DashboardEmptyStateProps {
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}

export function DashboardEmptyState({ title, description, action, className }: DashboardEmptyStateProps) {
  return (
    <Alert className={cn('border-dashed', className)}>
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className='mt-1 flex flex-col gap-3 text-sm'>
        <span>{description}</span>
        {action}
      </AlertDescription>
    </Alert>
  );
}
