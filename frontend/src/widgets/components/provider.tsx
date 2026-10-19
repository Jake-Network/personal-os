'use client';

import { ReactNode } from 'react';

import { QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from 'next-themes';

import { SecurityGate } from '@/features/security/security-gate';

import { ConfirmProvider } from '@/components/confirm-dialog';

import { Toaster } from '@/components/ui/sonner';

import { getQueryClient } from '@/lib/react-query-hooks';

import { TimezoneGate } from './timezone-gate';

export default function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={getQueryClient()}>
      <ThemeProvider attribute='class' defaultTheme='system' enableSystem disableTransitionOnChange>
        <Toaster position='bottom-right' />
        <SecurityGate>
          <TimezoneGate>
            <ConfirmProvider>{children}</ConfirmProvider>
          </TimezoneGate>
        </SecurityGate>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
