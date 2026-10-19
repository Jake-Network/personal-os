import type { Metadata } from 'next';

import { DisplaySettings } from '@/features/settings/components/display-settings';

export const metadata: Metadata = { title: '화면' };

export default function Page() {
  return <DisplaySettings />;
}
