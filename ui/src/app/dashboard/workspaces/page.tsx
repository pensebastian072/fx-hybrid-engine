'use client';

import PageContainer from '@/components/layout/page-container';
import { DashboardEmptyState } from '@/components/dashboard/empty-state';
import { OrganizationList } from '@clerk/nextjs';
import { dark } from '@clerk/themes';
import { useTheme } from 'next-themes';
import { workspacesInfoContent } from '@/config/infoconfig';
import { clerkAuthEnabled } from '@/lib/auth-config';

export default function WorkspacesPage() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <PageContainer
      pageTitle='Workspaces'
      pageDescription='Manage your workspaces and switch between them'
      infoContent={workspacesInfoContent}
    >
      {!clerkAuthEnabled ? (
        <DashboardEmptyState
          title='Workspaces unavailable'
          description='Workspace management is disabled in local no-auth mode.'
        />
      ) : (
        <OrganizationList
          appearance={{
            baseTheme: isDark ? dark : undefined,
            elements: {
              organizationListBox: 'space-y-2',
              organizationPreview: 'rounded-lg border p-4 hover:bg-accent',
              organizationPreviewMainIdentifier: 'text-lg font-semibold',
              organizationPreviewSecondaryIdentifier:
                'text-sm text-muted-foreground'
            }
          }}
          afterSelectOrganizationUrl='/dashboard/workspaces/team'
          afterCreateOrganizationUrl='/dashboard/workspaces/team'
        />
      )}
    </PageContainer>
  );
}
