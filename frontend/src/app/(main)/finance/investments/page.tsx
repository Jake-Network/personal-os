import type { Metadata } from 'next';

import { InvestmentsView } from '@/features/holdings/holdings-view';

export const metadata: Metadata = { title: '투자' };

export default function Page() {
  return <InvestmentsView />;
}
