import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { AccountValuationStatus, Spendability } from './account-valuation';
import type { FinanceLine } from './api';

const line = { issues: [], spendable: false } as unknown as FinanceLine;
describe('account valuation feedback', () => {
  it('requires a successful matching valuation before confirming a record', () => {
    const render = (props: Parameters<typeof AccountValuationStatus>[0]) => renderToStaticMarkup(createElement(AccountValuationStatus, props));
    expect(render({ line, pending: false, failed: true })).toContain('확인 실패');
    expect(render({ line, pending: true, failed: false })).toContain('확인 중');
    expect(render({ pending: false, failed: false })).toContain('확인 필요');
    expect(render({ line, pending: false, failed: false })).toContain('확인됨');
    expect(render({ line: { ...line, issues: ['Stale balance/quantity'] }, pending: false, failed: false })).not.toContain('확인됨');
  });
  it('displays the server policy result and preserves unknown eligibility', () => {
    const render = (spendable?: boolean) => renderToStaticMarkup(createElement(Spendability, { spendable }));
    expect(render(false)).toContain('제외');
    expect(render(true)).toContain('사용 가능');
    expect(render()).toContain('확인 필요');
  });
});
