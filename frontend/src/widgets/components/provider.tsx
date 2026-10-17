'use client';

import { ReactNode } from 'react';

import { QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from 'next-themes';

import { Toaster } from '@/components/ui/sonner';

import { getQueryClient } from '@/lib/react-query-hooks';

export default function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={getQueryClient()}>
      <ThemeProvider attribute='class' defaultTheme='system' enableSystem disableTransitionOnChange>
        <Toaster position='bottom-right' />
        {children}
      </ThemeProvider>
    </QueryClientProvider>
  );
}
