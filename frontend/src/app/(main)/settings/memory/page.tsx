import type { Metadata } from 'next';

import { MemoryView } from '@/features/memory/components/memory-view';

export const metadata: Metadata = { title: 'AI가 아는 나' };

export default function Page() {
  return <MemoryView />;
}
