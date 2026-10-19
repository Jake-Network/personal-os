import { describe, expect, it } from 'vitest';

import { type CalendarItem, itemSpan, layoutDay, monthMatrix, normalizeDays, shiftMonth, weekDays } from './calendar-utils';

const item = (over: Partial<CalendarItem>): CalendarItem => ({ key: 'x', title: 'x', start: '2026-10-18', allDay: true, tone: 'event', ...over });

describe('calendar grid', () => {
  it('builds Monday-first six-week months', () => {
    const m = monthMatrix('2026-10-18');
    expect(m).toHaveLength(6);
    expect(m[0][0]).toBe('2026-09-28');
    expect(m[0][3]).toBe('2026-10-01');
    expect(weekDays('2026-10-18')[0]).toBe('2026-10-12');
    expect(shiftMonth('2026-12-05', 1)).toBe('2027-01-01');
    expect(normalizeDays('2026-10-20', '2026-10-18')).toEqual({ start: '2026-10-18', end: '2026-10-20' });
  });

  it('places stored all-day spans on their local days', () => {
    // 10-17..10-18 in Seoul, stored as [10-17 00:00 KST, 10-19 00:00 KST)
    const holiday = item({ start: '2026-10-16T15:00:00Z', end: '2026-10-18T15:00:00Z' });
    expect(itemSpan(holiday, 'Asia/Seoul')).toEqual(['2026-10-17', '2026-10-18']);
    expect(itemSpan(item({ start: '2026-10-20' }))).toEqual(['2026-10-20', '2026-10-20']);
    const lateMeeting = item({ allDay: false, start: '2026-10-18T13:00:00Z', end: '2026-10-18T15:00:00Z' }); // 22:00–24:00 KST
    expect(itemSpan(lateMeeting, 'Asia/Seoul')).toEqual(['2026-10-18', '2026-10-18']);
  });

  it('lays overlapping timed items side by side and marks them', () => {
    const a = item({ key: 'a', allDay: false, start: '2026-10-18T00:00:00Z', end: '2026-10-18T01:00:00Z' }); // 09–10 KST
    const b = item({ key: 'b', allDay: false, start: '2026-10-18T00:30:00Z', end: '2026-10-18T02:00:00Z' });
    const c = item({ key: 'c', allDay: false, start: '2026-10-18T03:00:00Z' });
    const placed = layoutDay([a, b, c], '2026-10-18', 'Asia/Seoul');
    const by = Object.fromEntries(placed.map(p => [p.item.key, p]));
    expect([by.a.top, by.a.bottom, by.a.lane, by.a.lanes, by.a.conflict]).toEqual([540, 600, 0, 2, true]);
    expect([by.b.lane, by.b.conflict]).toEqual([1, true]);
    expect([by.c.top, by.c.bottom, by.c.lanes, by.c.conflict]).toEqual([720, 750, 1, false]);
  });
});
