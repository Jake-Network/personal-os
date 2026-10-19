import { afterEach, describe, expect, it } from 'vitest';

import { dateOnly, dateTime, money, moneyShort, monthLabel, setDisplayTimeZone } from './format';

describe('money', () => {
  it('formats KRW and foreign currencies from exact Decimal text', () => {
    expect(money('1234567')).toBe('1,234,567원');
    expect(money(12.5, 'USD')).toBe('12.5 USD');
    expect(money('98765432109876543210.10', 'USD')).toBe('98,765,432,109,876,543,210.1 USD');
  });

  it('keeps a missing amount distinct from zero', () => {
    expect(money(null)).toBe('미기록');
    expect(money(undefined, 'KRW', '공유 제외')).toBe('공유 제외');
    expect(money('0')).toBe('0원');
    expect(money('1e3')).toBe('확인 필요');
  });

  it('uses 억/만 units for headline figures', () => {
    expect(moneyShort(123_450_000)).toBe('1억 2,345만원');
    expect(moneyShort(-50_000)).toBe('-5만원');
    expect(moneyShort(null)).toBe('미기록');
  });
});

describe('dates', () => {
  afterEach(() => setDisplayTimeZone(undefined));

  it('shows instants in the backend timezone, not the browser one', () => {
    setDisplayTimeZone('Asia/Seoul');
    expect(dateOnly('2026-10-17T16:00:00Z')).toBe('2026. 10. 18.');
    setDisplayTimeZone('America/New_York');
    expect(dateOnly('2026-10-17T16:00:00Z')).toBe('2026. 10. 17.');
    expect(dateTime('2026-10-17T16:00:00Z')).toContain('12:00');
  });

  it('never shifts a calendar date', () => {
    setDisplayTimeZone('America/Los_Angeles');
    expect(dateOnly('2026-10-18')).toBe('2026. 10. 18.');
    expect(monthLabel('2026-03-31')).toBe('2026년 3월');
  });
});
