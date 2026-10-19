import type { Metadata } from 'next';

import { HistoryView } from '@/features/finance/history-view';

export const metadata: Metadata = { title: '월별 기록' };

export default function Page() {
  return <HistoryView />;
}
