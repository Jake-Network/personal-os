import { describe, expect, it } from 'vitest';

import { periodRange, periodTitle, previousPeriod } from './period';

describe('review periods', () => {
  it('builds half-open ranges, crossing a year end', () => {
    expect(periodRange('month', 2026, 12)).toEqual({ start_on: '2026-12-01', end_on: '2027-01-01' });
    expect(periodRange('quarter', 2026, 3)).toEqual({ start_on: '2026-07-01', end_on: '2026-10-01' });
    expect(periodRange('year', 2025)).toEqual({ start_on: '2025-01-01', end_on: '2026-01-01' });
  });

  it('names stored reviews and defaults to the last finished period', () => {
    expect(periodTitle('quarter', '2026-07-01')).toBe('2026년 3분기');
    expect(periodTitle('month', '2026-09-01')).toBe('2026년 9월');
    expect(previousPeriod('month', '2026-01-15')).toEqual({ year: 2025, index: 12 });
    expect(previousPeriod('quarter', '2026-10-19')).toEqual({ year: 2026, index: 3 });
  });
});
