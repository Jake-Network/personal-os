import type { Metadata } from 'next';

import { PrivacySettingsView } from '@/features/settings/components/privacy-settings';

export const metadata: Metadata = { title: '데이터 공유' };

export default function PrivacyPage() {
  return <PrivacySettingsView />;
}
