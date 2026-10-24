import { addDays, fromZonedInput, toZonedInput, zonedDayKey, zonedMidnight } from '@/lib/utils/zoned';
import { durationInput, durationSeconds } from '@/lib/utils/duration';

import type { FieldSpec } from './schema-fields';

export type FormValues = Record<string, string | boolean>;

/**
 * All-day calendar events are edited as first and last day; they are stored as the half-open span
 * [first day 00:00, day after the last 00:00) in PERSONAL_OS_TIMEZONE.
 */
export const ALL_DAY = { flag: 'all_day', start: 'starts_at', end: 'ends_at' } as const;

export function hasAllDay(fields: FieldSpec[]): boolean {
  return fields.some(f => f.name === ALL_DAY.flag) && fields.some(f => f.name === ALL_DAY.start);
}

export function initialValues(fields: FieldSpec[], current?: Record<string, unknown>): FormValues {
  const values: FormValues = Object.fromEntries(
    fields.map(f => {
      const v = current?.[f.name] !== undefined ? current[f.name] : f.defaultValue;
      if (f.kind === 'boolean') return [f.name, Boolean(v)];
      if (v === null || v === undefined) return [f.name, ''];
      if (f.kind === 'duration') return [f.name, durationInput(Number(v))];
      if (f.kind === 'datetime') return [f.name, toZonedInput(String(v))];
      return [f.name, String(v)];
    }),
  );
  return hasAllDay(fields) ? allDayInitial(values, current) : values;
}

/** Input text when the all-day switch flips: keep the day, pick a sensible time. */
export function toggleAllDayValue(value: string, allDay: boolean, fallbackTime: string): string {
  if (!value) return '';
  return allDay ? value.slice(0, 10) : `${value.slice(0, 10)}T${fallbackTime}`;
}

function allDayInitial(values: FormValues, current?: Record<string, unknown>): FormValues {
  if (!current?.[ALL_DAY.flag] || typeof current[ALL_DAY.start] !== 'string') return values;
  const start = zonedDayKey(current[ALL_DAY.start] as string);
  const end = typeof current[ALL_DAY.end] === 'string' ? addDays(zonedDayKey(current[ALL_DAY.end] as string), -1) : start;
  return { ...values, [ALL_DAY.start]: start, [ALL_DAY.end]: end < start ? start : end };
}

export function toPayload(fields: FieldSpec[], values: FormValues): Record<string, unknown> {
  if (hasAllDay(fields) && values[ALL_DAY.flag]) {
    const start = String(values[ALL_DAY.start]).slice(0, 10);
    const last = String(values[ALL_DAY.end] || start).slice(0, 10);
    const rest = toPayload(
      fields.filter(f => f.name !== ALL_DAY.start && f.name !== ALL_DAY.end),
      values,
    );
    return { ...rest, [ALL_DAY.start]: zonedMidnight(start), [ALL_DAY.end]: zonedMidnight(addDays(last < start ? start : last, 1)) };
  }
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.name];
    if (f.kind === 'duration') {
      out[f.name] = durationSeconds(String(v ?? ''));
      continue;
    }
    if (f.kind === 'boolean') {
      out[f.name] = Boolean(v);
      continue;
    }
    if (v === '' || v === undefined) {
      if (f.nullable) out[f.name] = null;
      continue; // let the server apply its default or report the missing field
    }
    if (f.kind === 'integer' && f.name !== 'quantity') out[f.name] = Number(v);
    else if (f.kind === 'datetime') out[f.name] = fromZonedInput(String(v)); // wall clock in PERSONAL_OS_TIMEZONE
    else out[f.name] = String(v).trim(); // decimals stay strings: no float rounding of money
  }
  return out;
}
