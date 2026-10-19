import type { Metadata } from 'next';

import { SecuritySettings } from '@/features/security/security-settings';

export const metadata: Metadata = { title: '보안·백업' };

export default function Page() {
  return <SecuritySettings />;
}
