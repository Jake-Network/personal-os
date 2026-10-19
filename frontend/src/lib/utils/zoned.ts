import { TZDate } from '@date-fns/tz';

import { displayTimeZone } from './format';

// Wall-clock arithmetic in the backend's PERSONAL_OS_TIMEZONE. Calendar days are 'YYYY-MM-DD' keys.

const pad = (n: number) => String(n).padStart(2, '0');

export function dayKeyOf(d: { getFullYear(): number; getMonth(): number; getDate(): number }): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The local day an instant falls on. */
export function zonedDayKey(iso: string, tz = displayTimeZone()): string {
  return dayKeyOf(new TZDate(iso, tz));
}

export function todayKey(tz = displayTimeZone(), now = new Date()): string {
  return dayKeyOf(new TZDate(now.getTime(), tz));
}

function parseKey(key: string): [number, number, number] {
  const [y, m, d] = key.split('-').map(Number);
  return [y, m - 1, d];
}

/** Pure calendar arithmetic; independent of any time zone. */
export function addDays(key: string, days: number): string {
  const [y, m, d] = parseKey(key);
  const date = new Date(Date.UTC(y, m, d + days));
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

export function compareKeys(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** 0 = Monday … 6 = Sunday. */
export function weekdayOf(key: string): number {
  const [y, m, d] = parseKey(key);
  return (new Date(Date.UTC(y, m, d)).getUTCDay() + 6) % 7;
}

/** The instant of local midnight starting `key` (UTC ISO). */
export function zonedMidnight(key: string, tz = displayTimeZone()): string {
  const [y, m, d] = parseKey(key);
  return new Date(new TZDate(y, m, d, 0, 0, tz).getTime()).toISOString();
}

/** An instant at a wall-clock minute of `key` (UTC ISO). */
export function zonedInstant(key: string, minutes: number, tz = displayTimeZone()): string {
  const [y, m, d] = parseKey(key);
  return new Date(new TZDate(y, m, d, Math.floor(minutes / 60), minutes % 60, tz).getTime()).toISOString();
}

/** Minutes after local midnight. */
export function zonedMinutes(iso: string, tz = displayTimeZone()): number {
  const d = new TZDate(iso, tz);
  return d.getHours() * 60 + d.getMinutes();
}

/** `datetime-local` input text for an instant. */
export function toZonedInput(iso: string, tz = displayTimeZone()): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const d = new TZDate(t, tz);
  return `${dayKeyOf(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** UTC ISO for `datetime-local` input text read as wall-clock time. */
export function fromZonedInput(text: string, tz = displayTimeZone()): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(text);
  if (!m) return new Date(text).toISOString();
  return zonedInstant(`${m[1]}-${m[2]}-${m[3]}`, Number(m[4]) * 60 + Number(m[5]), tz);
}
