import { AreaLayout } from '@/components/area-layout';

const TABS = [
  { href: '/career', label: '지원 현황', end: true },
  { href: '/career/records', label: '경력 기록' },
  { href: '/career/timeline', label: '타임라인' },
  { href: '/career/criteria', label: '평가 기준' },
];

export default function CareerLayout({ children }: { children: React.ReactNode }) {
  return (
    <AreaLayout title='커리어' tabs={TABS}>
      {children}
    </AreaLayout>
  );
}
