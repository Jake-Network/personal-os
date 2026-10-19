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
  currency: 'KRW',
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
  it('labels totals, categories, trends and excluded records in the response currency', () => {
    const html = render({
      ...response,
      currency: 'USD',
      summary: { income: null, expense: '12.5', net: '-12.5', record_count: 2, foreign_count: 1 },
      categories: [{ category: '식비', amount: '12.5', share: '100' }],
      trend: [{ month: '2026-09', income: null, expense: '12.5', net: '-12.5', record_count: 2, foreign_count: 1 }],
    });
    expect(html).toContain('12.5 USD');
    expect(html).not.toContain('12.5원');
    expect(html).toContain('다른 통화 기록 1건은 USD 합계에서 제외했습니다.');
  });
  it('shows a duplicate-entry warning when both sources contribute', () => {
    expect(render({ ...response, data_quality_flags: ['cashflow_mixed_sources'] })).toContain(
      '가계부와 거래 기록을 함께 합산했습니다. 같은 수입·지출을 중복 입력했는지 확인하세요.',
    );
  });
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
