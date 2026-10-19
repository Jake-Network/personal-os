import { addDays, compareKeys, weekdayOf, zonedDayKey, zonedMinutes } from '@/lib/utils/zoned';

export type CalendarTone = 'event' | 'interview' | 'task' | 'goal' | 'expense' | 'workout';

export interface CalendarItem {
  /** Unique across sources, e.g. `tasks:4`. */
  key: string;
  title: string;
  /** An ISO instant, or a 'YYYY-MM-DD' calendar date. */
  start: string;
  /** Exclusive end: an instant, or for all-day items the local midnight after the last day. */
  end?: string | null;
  allDay: boolean;
  tone: CalendarTone;
  done?: boolean;
  overdue?: boolean;
  /** Secondary text, e.g. a company or an amount. */
  detail?: string;
}

/** Days picked in the month grid (inclusive), or a time range on one day in the week grid. */
export type CalendarSelection = { kind: 'days'; start: string; end: string } | { kind: 'time'; day: string; startMinute: number; endMinute: number };

const isDateKey = (v: string) => /^\d{4}-\d{2}-\d{2}$/.test(v);

export function dayOf(value: string, tz?: string): string {
  return isDateKey(value) ? value : zonedDayKey(value, tz);
}

/** First and last day (inclusive) an item covers. */
export function itemSpan(item: CalendarItem, tz?: string): [string, string] {
  const first = dayOf(item.start, tz);
  if (!item.end) return [first, first];
  if (item.allDay) {
    const endExclusive = dayOf(item.end, tz);
    const last = addDays(endExclusive, -1);
    return [first, compareKeys(last, first) < 0 ? first : last];
  }
  // A timed item that ends exactly at midnight does not occupy the next day.
  const endDay = dayOf(item.end, tz);
  const endsAtMidnight = !isDateKey(item.end) && zonedMinutes(item.end, tz) === 0;
  const last = endsAtMidnight ? addDays(endDay, -1) : endDay;
  return [first, compareKeys(last, first) < 0 ? first : last];
}

export function coversDay(item: CalendarItem, day: string, tz?: string): boolean {
  const [first, last] = itemSpan(item, tz);
  return compareKeys(first, day) <= 0 && compareKeys(day, last) <= 0;
}

/** Monday-first weeks covering the month of `anchor`, always 6 rows so the grid doesn't jump. */
export function monthMatrix(anchor: string): string[][] {
  const first = `${anchor.slice(0, 7)}-01`;
  const start = addDays(first, -weekdayOf(first));
  return Array.from({ length: 6 }, (_, w) => Array.from({ length: 7 }, (_, d) => addDays(start, w * 7 + d)));
}

export function weekDays(anchor: string): string[] {
  const start = addDays(anchor, -weekdayOf(anchor));
  return Array.from({ length: 7 }, (_, d) => addDays(start, d));
}

export function shiftMonth(anchor: string, months: number): string {
  const [y, m] = anchor.split('-').map(Number);
  const total = y * 12 + (m - 1) + months;
  return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, '0')}-01`;
}

export function normalizeDays(a: string, b: string): { start: string; end: string } {
  return compareKeys(a, b) <= 0 ? { start: a, end: b } : { start: b, end: a };
}

export function sortItems(items: CalendarItem[]): CalendarItem[] {
  return [...items].sort((a, b) => Number(b.allDay) - Number(a.allDay) || a.start.localeCompare(b.start) || a.title.localeCompare(b.title));
}

export interface PlacedItem {
  item: CalendarItem;
  top: number;
  bottom: number;
  lane: number;
  lanes: number;
  conflict: boolean;
}

/** Timed items of one day in minutes, laid out in side-by-side lanes where they overlap. */
export function layoutDay(items: CalendarItem[], day: string, tz?: string, minDuration = 30): PlacedItem[] {
  const placed = items
    .filter(i => !i.allDay && !isDateKey(i.start) && coversDay(i, day, tz))
    .map(item => {
      const startDay = dayOf(item.start, tz);
      const top = startDay === day ? zonedMinutes(item.start, tz) : 0;
      let bottom = 24 * 60;
      if (item.end && dayOf(item.end, tz) === day) bottom = zonedMinutes(item.end, tz);
      else if (!item.end) bottom = top + minDuration;
      return { item, top, bottom: Math.max(bottom, top + Math.min(minDuration, 24 * 60 - top)), lane: 0, lanes: 1, conflict: false };
    })
    .sort((a, b) => a.top - b.top || b.bottom - a.bottom);

  let cluster: PlacedItem[] = [];
  let clusterEnd = -1;
  const flush = () => {
    const lanes = Math.max(1, ...cluster.map(p => p.lane + 1));
    for (const p of cluster) {
      p.lanes = lanes;
      p.conflict = cluster.length > 1;
    }
    cluster = [];
  };
  for (const p of placed) {
    if (p.top >= clusterEnd && cluster.length) flush();
    const used = new Set(cluster.filter(c => c.bottom > p.top).map(c => c.lane));
    let lane = 0;
    while (used.has(lane)) lane++;
    p.lane = lane;
    cluster.push(p);
    clusterEnd = Math.max(clusterEnd, p.bottom);
  }
  if (cluster.length) flush();
  return placed;
}

/** Timed items that overlap another item on the same day (shown as a conflict marker). */
export function conflictingKeys(items: CalendarItem[], days: string[], tz?: string): Set<string> {
  const out = new Set<string>();
  for (const day of days) for (const p of layoutDay(items, day, tz, 1)) if (p.conflict) out.add(p.item.key);
  return out;
}
