'use client';

import { SourceCalendar } from './source-calendar';

/** Everything with a date, in one calendar. */
export function PlanCalendar() {
  return <SourceCalendar sources={['calendar-events', 'interviews', 'tasks', 'goals', 'planned-expenses', 'workout-logs']} layers />;
}
