import { describe, expect, it } from 'vitest';

import { money, moneyShort } from './format';

describe('money', () => {
  it('formats KRW and foreign currencies', () => {
    expect(money('1234567')).toBe('1,234,567원');
    expect(money(12.5, 'USD')).toBe('12.5 USD');
    expect(money(null)).toBe('—');
  });

  it('uses 억/만 units for headline figures', () => {
    expect(moneyShort(123_450_000)).toBe('1억 2,345만원');
    expect(moneyShort(-50_000)).toBe('-5만원');
  });
});
