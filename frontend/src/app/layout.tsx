import type { Metadata, Viewport } from 'next';
import localFont from 'next/font/local';

import Providers from '@/widgets/components/provider';

import './globals.css';

const pretendard = localFont({
  src: '../../node_modules/pretendard/dist/web/variable/woff2/PretendardVariable.woff2',
  weight: '45 920',
  display: 'swap',
  variable: '--font-pretendard',
});

export const metadata: Metadata = {
  title: { default: 'Personal OS', template: '%s | Personal OS' },
  description: '자산·커리어·일정·목표를 한곳에서 보고 상담하는 개인 대시보드',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  colorScheme: 'light dark',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang='ko' className={pretendard.variable} suppressHydrationWarning>
      <body className='font-sans'>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
