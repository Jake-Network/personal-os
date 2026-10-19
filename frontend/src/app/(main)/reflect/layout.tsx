import { AreaLayout } from '@/components/area-layout';

const TABS = [
  { href: '/reflect', label: '결정 기록', end: true },
  { href: '/reflect/memory', label: '기억' },
  { href: '/reflect/reviews', label: '기간 회고' },
];

export default function ReflectLayout({ children }: { children: React.ReactNode }) {
  return (
    <AreaLayout title='기록·회고' tabs={TABS}>
      {children}
    </AreaLayout>
  );
}
