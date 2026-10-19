import type { Metadata } from 'next';

import { MemoryView } from '@/features/memory/components/memory-view';

export const metadata: Metadata = { title: '기억' };

export default function Page() {
  return <MemoryView />;
}
