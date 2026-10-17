import type { Metadata } from 'next';

import { MemoryView } from '@/features/memory/components/memory-view';

export const metadata: Metadata = { title: '기억 · 의사결정' };

export default function MemoryPage() {
  return <MemoryView />;
}
