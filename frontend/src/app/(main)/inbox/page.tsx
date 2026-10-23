import type { Metadata } from 'next';

import { InboxView } from '@/features/inbox/inbox-view';

export const metadata: Metadata = { title: '알림' };

export default function Page() {
  return <InboxView />;
}
