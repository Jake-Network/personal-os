import type { CalendarItem, CalendarSelection, CalendarTone } from '@/components/calendar/calendar-utils';
import { money } from '@/lib/utils/format';
import { formatDuration } from '@/lib/utils/duration';
import { addDays, compareKeys, todayKey, zonedInstant, zonedMidnight } from '@/lib/utils/zoned';

import type { Row } from '@/features/personal-data/api/resource-api';
import { enumLabel } from '@/features/personal-data/consts/resources';

export type SourceId = 'calendar-events' | 'interviews' | 'tasks' | 'goals' | 'planned-expenses' | 'workout-logs';

export interface CalendarSource {
  id: SourceId;
  label: string;
  tone: CalendarTone;
  /** Where the record lives, for deep links. */
  path: string;
  /** Whether a picked time of day means something for this record. */
  timed: boolean;
  toItems: (rows: Row[], ctx: { today: string; applications?: Map<number, Row> }) => CalendarItem[];
  /** Form values for a new record at the picked day(s) or time, and a note when part of the pick is unused. */
  defaults: (selection: CalendarSelection) => { values: Record<string, unknown>; note?: string };
}

const str = (v: unknown) => (typeof v === 'string' && v ? v : null);

function singleDay(field: string, label: string) {
  return (selection: CalendarSelection) => {
    if (selection.kind === 'time') return { values: { [field]: selection.day } };
    const ranged = selection.start !== selection.end;
    return { values: { [field]: selection.start }, note: ranged ? `${label}은(는) 하루만 지정할 수 있어 첫날로 넣었습니다.` : undefined };
  };
}

export const SOURCES: Record<SourceId, CalendarSource> = {
  'calendar-events': {
    id: 'calendar-events',
    label: '일정',
    tone: 'event',
    path: '/plan/events',
    timed: true,
    toItems: rows =>
      rows.flatMap(r =>
        str(r.starts_at)
          ? [{ key: `calendar-events:${r.id}`, title: String(r.title), start: r.starts_at as string, end: str(r.ends_at), allDay: Boolean(r.all_day), tone: r.kind === 'interview' ? 'interview' : 'event', detail: str(r.location) ?? undefined } satisfies CalendarItem]
          : [],
      ),
    defaults: selection =>
      selection.kind === 'days'
        ? { values: { all_day: true, starts_at: zonedMidnight(selection.start), ends_at: zonedMidnight(addDays(selection.end, 1)) } }
        : { values: { all_day: false, starts_at: zonedInstant(selection.day, selection.startMinute), ends_at: zonedInstant(selection.day, selection.endMinute) } },
  },
  interviews: {
    id: 'interviews',
    label: '면접',
    tone: 'interview',
    path: '/career',
    timed: true,
    toItems: (rows, { applications }) =>
      rows.flatMap(r => {
        if (!str(r.starts_at)) return [];
        const app = applications?.get(Number(r.application_id));
        const title = app ? `${app.company} ${r.stage}` : `면접 ${r.stage}`;
        return [{ key: `interviews:${r.id}`, title, start: r.starts_at as string, end: str(r.ends_at), allDay: false, tone: 'interview', detail: str(r.location) ?? undefined } satisfies CalendarItem];
      }),
    defaults: selection =>
      selection.kind === 'time'
        ? { values: { starts_at: zonedInstant(selection.day, selection.startMinute), ends_at: zonedInstant(selection.day, selection.endMinute) } }
        : { values: { starts_at: zonedInstant(selection.start, 10 * 60) }, note: '시작 시각을 10:00으로 넣었습니다. 실제 시각으로 바꾸세요.' },
  },
  tasks: {
    id: 'tasks',
    label: '할 일',
    tone: 'task',
    path: '/plan/tasks',
    timed: false,
    toItems: (rows, { today }) =>
      rows.flatMap(r =>
        str(r.due_on)
          ? [{ key: `tasks:${r.id}`, title: String(r.title), start: r.due_on as string, allDay: true, tone: 'task', done: r.status === 'done', overdue: r.status !== 'done' && compareKeys(r.due_on as string, today) < 0 } satisfies CalendarItem]
          : [],
      ),
    defaults: singleDay('due_on', '마감일'),
  },
  goals: {
    id: 'goals',
    label: '목표',
    tone: 'goal',
    path: '/plan/goals',
    timed: false,
    toItems: rows =>
      rows.flatMap(r =>
        str(r.target_date) && r.status !== 'dropped'
          ? [{ key: `goals:${r.id}`, title: `목표일 · ${r.title}`, start: r.target_date as string, allDay: true, tone: 'goal', done: r.status === 'done' } satisfies CalendarItem]
          : [],
      ),
    defaults: singleDay('target_date', '목표일'),
  },
  'planned-expenses': {
    id: 'planned-expenses',
    label: '예정 지출',
    tone: 'expense',
    path: '/finance/cashflow?source=planned_expenses',
    timed: false,
    toItems: (rows, { today }) =>
      rows.flatMap(r =>
        str(r.due_on)
          ? [{ key: `planned-expenses:${r.id}`, title: String(r.name), start: r.due_on as string, allDay: true, tone: 'expense', detail: money(r.amount as string, (r.currency as string) ?? 'KRW'), overdue: compareKeys(r.due_on as string, today) < 0 } satisfies CalendarItem]
          : [],
      ),
    defaults: singleDay('due_on', '지급일'),
  },
  'workout-logs': {
    id: 'workout-logs',
    label: '운동',
    tone: 'workout',
    path: '/plan/workouts',
    timed: false,
    toItems: rows =>
      rows.flatMap(r =>
        str(r.performed_on)
          ? [{ key: `workout-logs:${r.id}`, title: `${r.activity} ${formatDuration(r.duration_seconds)}`, start: r.performed_on as string, allDay: true, tone: 'workout', detail: r.intensity ? enumLabel(r.intensity) : undefined } satisfies CalendarItem]
          : [],
      ),
    defaults: singleDay('performed_on', '운동일'),
  },
};

export function itemRef(key: string): { source: SourceId; id: number } {
  const i = key.lastIndexOf(':');
  return { source: key.slice(0, i) as SourceId, id: Number(key.slice(i + 1)) };
}

export function calendarToday() {
  return todayKey();
}
