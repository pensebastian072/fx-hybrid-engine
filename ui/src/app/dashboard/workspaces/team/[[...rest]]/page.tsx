'use client';

import PageContainer from '@/components/layout/page-container';
import { DashboardEmptyState } from '@/components/dashboard/empty-state';
import { OrganizationProfile } from '@clerk/nextjs';
import { dark } from '@clerk/themes';
import { useTheme } from 'next-themes';
import { teamInfoContent } from '@/config/infoconfig';
import { clerkAuthEnabled } from '@/lib/auth-config';

export default function TeamPage() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <PageContainer
      pageTitle='Team Management'
      pageDescription='Manage your workspace team, members, roles, security and more.'
      infoContent={teamInfoContent}
    >
      {!clerkAuthEnabled ? (
        <DashboardEmptyState
          title='Team management unavailable'
          description='Organization administration is disabled in local no-auth mode.'
        />
      ) : (
        <OrganizationProfile
          appearance={{
            baseTheme: isDark ? dark : undefined
          }}
        />
      )}
    </PageContainer>
  );
}
