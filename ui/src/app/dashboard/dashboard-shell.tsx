'use client';

import dynamic from 'next/dynamic';
import { SidebarInset } from '@/components/ui/sidebar';

const AppSidebar = dynamic(() => import('@/components/layout/app-sidebar'), { ssr: false });
const Header = dynamic(() => import('@/components/layout/header'), { ssr: false });
const InfoSidebar = dynamic(
  () => import('@/components/layout/info-sidebar').then((m) => ({ default: m.InfoSidebar })),
  { ssr: false }
);

export function DashboardShell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AppSidebar />
      <SidebarInset>
        <Header />
        {children}
      </SidebarInset>
      <InfoSidebar side='right' />
    </>
  );
}
