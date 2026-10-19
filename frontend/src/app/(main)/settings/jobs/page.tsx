import type { Metadata } from 'next';

import { JobsView } from '@/features/reviews/jobs-view';

export const metadata: Metadata = { title: '자동 작업' };

export default function Page() {
  return <JobsView />;
}
