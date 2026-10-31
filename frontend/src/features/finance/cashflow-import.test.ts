import { describe, expect, it } from 'vitest';

import { decodeCsvBytes, guessMapping, headerColumns, sourceIdFrom } from './cashflow-import';

describe('cashflow import helpers', () => {
  it('decodes UTF-8 and falls back to EUC-KR', () => {
    expect(decodeCsvBytes(new TextEncoder().encode('거래일,금액').buffer)).toBe('거래일,금액');
    // "일자" in EUC-KR is not valid UTF-8.
    const eucKr = new Uint8Array([0xc0, 0xcf, 0xc0, 0xda]).buffer;
    expect(decodeCsvBytes(eucKr)).toBe('일자');
  });

  it('reads the header after preamble lines with quoted cells and tabs', () => {
    expect(headerColumns('﻿거래일,"이용, 금액",가맹점\n2026-01-01,1,a', 0)).toEqual(['거래일', '이용, 금액', '가맹점']);
    expect(headerColumns('Synthetic Bank\n일자\t적요\t출금\t입금\n', 1)).toEqual(['일자', '적요', '출금', '입금']);
    expect(headerColumns('only one line', 3)).toEqual([]);
  });

  it('guesses one amount shape from common header names', () => {
    expect(guessMapping(['거래일', '가맹점명', '이용금액', '업종'])).toEqual({
      date: '거래일',
      amount: '이용금액',
      description: '가맹점명',
      category: '업종',
    });
    expect(guessMapping(['일자', '적요', '금액', '출금', '입금'])).toEqual({ date: '일자', debit: '출금', credit: '입금', description: '적요' });
  });

  it('derives a stable source ID from a filename', () => {
    expect(sourceIdFrom('synthetic card 2026-08.csv')).toBe('synthetic-card-2026-08');
    expect(sourceIdFrom('카드내역.csv')).toBe('csv');
  });
});
