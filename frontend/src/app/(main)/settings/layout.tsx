import { AreaLayout } from '@/components/area-layout';

const TABS = [
  { href: '/settings/ai-provider', label: 'AI 연결' },
  { href: '/settings/privacy', label: '데이터 공유' },
  { href: '/settings/market', label: '시세 연결' },
  { href: '/settings/jobs', label: '자동 작업' },
  { href: '/settings/security', label: '보안·백업' },
  { href: '/settings/display', label: '화면' },
];

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <AreaLayout title='설정' tabs={TABS}>
      {children}
    </AreaLayout>
  );
}
