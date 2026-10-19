import { describe, expect, it } from 'vitest';

import { addDays, fromZonedInput, todayKey, weekdayOf, zonedDayKey, zonedMidnight } from './zoned';

describe('zoned calendar days', () => {
  it('buckets instants by the configured local day', () => {
    expect(zonedDayKey('2026-10-17T16:00:00Z', 'Asia/Seoul')).toBe('2026-10-18');
    expect(zonedDayKey('2026-10-17T16:00:00Z', 'America/New_York')).toBe('2026-10-17');
    expect(todayKey('Asia/Seoul', new Date('2026-10-17T23:00:00Z'))).toBe('2026-10-18');
  });

  it('builds local midnights, including across a DST change', () => {
    expect(zonedMidnight('2026-10-18', 'Asia/Seoul')).toBe('2026-10-17T15:00:00.000Z');
    expect(zonedMidnight('2026-11-01', 'America/New_York')).toBe('2026-11-01T04:00:00.000Z');
    expect(zonedMidnight('2026-11-02', 'America/New_York')).toBe('2026-11-02T05:00:00.000Z');
    expect(fromZonedInput('2026-10-18T09:00', 'Asia/Seoul')).toBe('2026-10-18T00:00:00.000Z');
  });

  it('does pure day arithmetic', () => {
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28');
    expect(weekdayOf('2026-10-19')).toBe(0); // Monday
  });
});
