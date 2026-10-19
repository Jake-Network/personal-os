import { AreaLayout } from '@/components/area-layout';

const TABS = [
  { href: '/plan', label: '달력', end: true },
  { href: '/plan/tasks', label: '할 일' },
  { href: '/plan/events', label: '일정' },
  { href: '/plan/goals', label: '목표' },
  { href: '/plan/workouts', label: '운동' },
];

export default function PlanLayout({ children }: { children: React.ReactNode }) {
  return (
    <AreaLayout title='할 일·일정' tabs={TABS}>
      {children}
    </AreaLayout>
  );
}
