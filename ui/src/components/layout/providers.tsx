'use client';
import { ClerkProvider } from '@clerk/nextjs';
import { dark } from '@clerk/themes';
import { useTheme } from 'next-themes';
import React from 'react';
import { ActiveThemeProvider } from '../themes/active-theme';
import { clerkAuthEnabled, clerkPublishableKey } from '@/lib/auth-config';

export default function Providers({
  activeThemeValue,
  children
}: {
  activeThemeValue: string;
  children: React.ReactNode;
}) {
  // we need the resolvedTheme value to set the baseTheme for clerk based on the dark or light theme
  const { resolvedTheme } = useTheme();

  if (!clerkAuthEnabled) {
    return <ActiveThemeProvider initialTheme={activeThemeValue}>{children}</ActiveThemeProvider>;
  }

  return (
    <>
      <ActiveThemeProvider initialTheme={activeThemeValue}>
        <ClerkProvider
          publishableKey={clerkPublishableKey}
          appearance={{
            baseTheme: resolvedTheme === 'dark' ? dark : undefined
          }}
        >
          {children}
        </ClerkProvider>
      </ActiveThemeProvider>
    </>
  );
}
