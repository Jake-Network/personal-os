import type { Metadata } from 'next';

import { PlanCalendar } from '@/features/plan/plan-calendar';

export const metadata: Metadata = { title: '달력' };

export default function Page() {
  return <PlanCalendar />;
}
