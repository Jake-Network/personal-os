import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import type { CashflowResponse } from '@/api-client/model/cashflowResponse';
import { todayKey } from '@/lib/utils/zoned';

import { CashflowView } from './cashflow-view';

function render(data: CashflowResponse) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(['finance', 'cashflow', todayKey().substring(0, 7), '', '', '', 1], data);
  return renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(CashflowView, { recordId: null })));
}

const response: CashflowResponse = {
  month: '2026-10',
  items: [],
  total: 0,
  page: 1,
  page_size: 50,
  summary: { income: null, expense: null, net: null, record_count: 0, foreign_count: 0 },
  categories: [],
  trend: [],
  data_quality_flags: [],
};

describe('household ledger view', () => {
  it('uses backend totals beyond the current page and distinguishes missing values from zero', () => {
    const html = render({
      ...response,
      total: 1200,
      summary: { income: '0.00', expense: '1234567.89', net: '-1234567.89', record_count: 1200, foreign_count: 1 },
      trend: [{ month: '2026-09', income: null, expense: null, net: null, record_count: 0, foreign_count: 0 }],
    });
    expect(html).toContain('1,234,567.89원');
    expect(html).toContain('0원');
    expect(html).toContain('미기록');
    expect(html).toContain('외화 기록 1건은 원화 합계에서 제외했습니다.');
    expect(html).toContain('1 / 24');
  });

  it('offers edit for ordinary records and cancellation for ledger records sharing the same id', () => {
    const common = {
      id: 7,
      occurred_on: '2026-10-01',
      kind: 'expense' as const,
      original_kind: 'expense',
      amount: '100',
      currency: 'KRW',
      category: '식비',
      is_reversed: false,
    };
    const html = render({
      ...response,
      total: 2,
      items: [
        { ...common, source: 'cashflow_entries', description: '점심' },
        { ...common, source: 'financial_transactions', description: '저녁' },
      ],
    });
    expect(html).toContain('aria-label="점심 수정"');
    expect(html).toContain('aria-label="저녁 거래 취소"');
    expect(html).not.toContain('aria-label="저녁 수정"');
  });
});
