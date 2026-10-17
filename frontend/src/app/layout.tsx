import type { Metadata, Viewport } from 'next';

import Providers from '@/widgets/components/provider';

import './globals.css';

export const metadata: Metadata = {
  title: { default: 'Personal OS', template: '%s | Personal OS' },
  description: '나의 실제 상황을 아는 AI 상담',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  colorScheme: 'light dark',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang='ko' suppressHydrationWarning>
      <body className='font-sans'>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
