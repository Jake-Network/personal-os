import { describe, expect, it } from 'vitest';

import { returnPercent, returnTone, signedMoney } from './presentation';

describe('holding return presentation', () => {
  it('distinguishes unknown values, break-even, gains and losses without using color alone', () => {
    expect(returnPercent(null)).toBe('수익률 확인 필요');
    expect(returnPercent('0')).toBe('0.00%');
    expect(returnPercent('12.345')).toBe('+12.35%');
    expect(returnPercent('-7.5')).toBe('-7.50%');
    expect(returnTone('-0.000')).toBe('neutral');
    expect(returnTone('0.0001')).toBe('positive');
    expect(returnTone('-1')).toBe('negative');
    expect(returnTone('NaN')).toBe('neutral');
    expect(returnPercent('NaN')).toBe('수익률 확인 필요');
  });

  it('preserves native currency and exact profit amounts, including large values', () => {
    expect(signedMoney('12345678901234567890.123', 'USD')).toBe('+12,345,678,901,234,567,890.123 USD');
    expect(signedMoney('-1000', 'KRW')).toBe('-1,000원');
    expect(signedMoney('0', 'USD')).toBe('0 USD');
    expect(signedMoney(null, 'USD')).toBe('확인 필요');
  });
});
