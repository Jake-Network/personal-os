import type { Metadata } from 'next';

import { TimelineView } from '@/features/career/timeline-view';

export const metadata: Metadata = { title: '타임라인' };

export default function Page() {
  return <TimelineView />;
}
