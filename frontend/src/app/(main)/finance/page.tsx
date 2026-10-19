import type { Metadata } from 'next';

import { PortfolioView } from '@/features/finance/portfolio-view';

export const metadata: Metadata = { title: '자산' };

export default function Page() {
  return <PortfolioView />;
}
