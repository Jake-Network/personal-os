import { expect, it } from 'vitest';
import { recordOptions } from './record-options';
import { toPayload } from './form-values';
import { setDisplayTimeZone } from '@/lib/utils/format';

it('keeps duplicate named records distinct and submits the selected stable ID', () => {
  const options = recordOptions([
    { id: 7, name: '생활비' },
    { id: 12, name: '생활비' },
  ]);
  expect(options).toEqual([
    { value: '7', label: '생활비 (1)' },
    { value: '12', label: '생활비 (2)' },
  ]);
  expect(toPayload([{ name: 'account_id', kind: 'integer', required: false, nullable: true }], { account_id: options[1].value })).toEqual({
    account_id: 12,
  });
});

it('identifies job applications by company and role', () => {
  expect(recordOptions([{ id: 3, company: '예시 회사', role: '백엔드' }])[0].label).toBe('예시 회사 · 백엔드');
});

it('distinguishes project titles at the same company', () => {
  const choices = recordOptions([
    { id: 1, company: '예시 회사', title: '검색 개선' },
    { id: 2, company: '예시 회사', title: '정산 개편' },
  ]);
  expect(choices.map(o => o.label)).toEqual(['예시 회사 · 검색 개선', '예시 회사 · 정산 개편']);
});

it('identifies transactions by date, kind, exact amount and note', () => {
  setDisplayTimeZone('Asia/Seoul');
  try {
    expect(
      recordOptions([{ id: 9, occurred_at: '2026-10-01T03:00:00Z', kind: 'expense', amount: '200000.10', currency: 'KRW', note: '생활비' }])[0].label,
    ).toBe('2026. 10. 1. · 지출 · 200000.10 KRW · 생활비');
  } finally {
    setDisplayTimeZone(undefined);
  }
});
