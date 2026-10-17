import type { Metadata } from 'next';
import { PortfolioView } from '@/features/finance/portfolio-view';

export const metadata: Metadata = { title: '포트폴리오' };

export default function FinancePage() {
  return <PortfolioView />;
}
