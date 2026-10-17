import type { Metadata } from 'next';

import { ApprovalsView } from '@/features/approvals/components/approvals-view';

export const metadata: Metadata = { title: '승인 대기' };

export default function ApprovalsPage() {
  return <ApprovalsView />;
}
