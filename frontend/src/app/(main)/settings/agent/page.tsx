import type { Metadata } from 'next';

import { AgentSettings } from '@/features/settings/components/agent-settings';

export const metadata: Metadata = { title: '상담 방식' };

export default function Page() {
  return <AgentSettings />;
}
