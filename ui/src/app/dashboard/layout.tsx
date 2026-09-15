import KBar from '@/components/kbar';
import { InfobarProvider } from '@/components/ui/infobar';
import { SidebarProvider } from '@/components/ui/sidebar';
import type { Metadata } from 'next';
import { cookies } from 'next/headers';
import { DashboardShell } from './dashboard-shell';

export const metadata: Metadata = {
  title: 'FX Hybrid Engine Dashboard',
  description: 'FX Hybrid Engine — Algo trading monitor',
  robots: {
    index: false,
    follow: false
  }
};

export default async function DashboardLayout({
  children
}: {
  children: React.ReactNode;
}) {
  // Persisting the sidebar state in the cookie.
  let defaultOpen = false;

  try {
    const cookieStore = await cookies();
    defaultOpen = cookieStore.get('sidebar_state')?.value === 'true';
  } catch {
    defaultOpen = false;
  }

  return (
    <KBar>
      <SidebarProvider defaultOpen={defaultOpen}>
        <InfobarProvider defaultOpen={false}>
          <DashboardShell>
            {children}
          </DashboardShell>
        </InfobarProvider>
      </SidebarProvider>
    </KBar>
  );
}
