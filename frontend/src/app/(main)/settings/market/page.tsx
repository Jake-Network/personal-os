import type { Metadata } from 'next';

import { MarketSettings } from '@/features/finance/market-settings';

export const metadata: Metadata = { title: '시세 연결' };

export default function Page() {
  return <MarketSettings />;
}
