import { describe, expect, it } from 'vitest';

import { adjacentMonths, allocationPercent, axisTicks, chartSegments, issueText, money } from './presentation';

describe('finance presentation', () => {
  it('keeps unknown values distinct from a real zero and preserves Decimal precision', () => {
    expect(money(null)).toBe('확인 필요');
    expect(money('')).toBe('확인 필요');
    expect(money('0')).toBe('0원');
    expect(money('12.50', 'USD')).toBe('12.5 USD');
    expect(money('12345678901234567890.123456789')).toBe('12,345,678,901,234,567,890.123456789원');
    expect(money('abc')).toBe('확인 필요');
  });

  it('recognizes only consecutive months including a year boundary', () => {
    expect(adjacentMonths('2025-12-31', '2026-01-31')).toBe(true);
    expect(adjacentMonths('2026-01-31', '2026-03-31')).toBe(false);
  });

  it('calculates allocation without losing Decimal precision or inventing zero denominators', () => {
    expect(allocationPercent('1', '3')).toBe('33.33%');
    expect(allocationPercent('0', '0')).toBe('비율 계산 불가');
    expect(allocationPercent(null, '10')).toBe('비율 확인 필요');
    expect(allocationPercent('12345678901234567890.1', '24691357802469135780.2')).toBe('50.00%');
  });

  it('does not connect chart values across missing records or incomplete valuations', () => {
    const points = [
      { month: '2026-01-31', value: '10' },
      { month: '2026-02-28', value: null },
      { month: '2026-03-31', value: '30' },
      { month: '2026-05-31', value: '40' },
    ];
    expect(chartSegments(points, 10, 40)).toHaveLength(3);
    expect(chartSegments([{ month: '2026-01-31', value: '0' }], 0, 0)[0]).toContain('M 400 180');
  });
});

describe('finance findings and axis', () => {
  it('translates valuation findings and keeps the item label', () => {
    expect(issueText('월급통장: Stale balance/quantity')).toBe('월급통장: 잔액·수량 기준일이 오래됨');
    expect(issueText('Missing explicit liability coverage')).toBe('부채 항목을 모두 입력했는지 확인 전');
    expect(issueText('Apple: Missing or invalid FX evidence')).toBe('Apple: 원화 환율 없음');
    expect(issueText('Something new')).toBe('Something new');
  });

  it('picks round ticks that cover the range', () => {
    expect(axisTicks(0, 100_000_000)).toEqual([0, 25_000_000, 50_000_000, 75_000_000, 100_000_000]);
    expect(axisTicks(0, 37)).toEqual([0, 10, 20, 30]);
    expect(axisTicks(5, 5)).toEqual([5]);
  });
});
