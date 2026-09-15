import { DashboardEmptyState } from '@/components/dashboard/empty-state';
import { clerkAuthEnabled } from '@/lib/auth-config';
import { UserProfile } from '@clerk/nextjs';

export default function ProfileViewPage() {
  if (!clerkAuthEnabled) {
    return (
      <div className='flex w-full flex-col p-4'>
        <DashboardEmptyState
          title='Profile unavailable'
          description='Profile management is disabled in local no-auth mode.'
        />
      </div>
    );
  }

  return (
    <div className='flex w-full flex-col p-4'>
      <UserProfile />
    </div>
  );
}
