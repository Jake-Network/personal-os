import { expect, it } from 'vitest';
import { flagDetail, flagText } from './labels';
it('explains withheld history and limited search without internal codes', () => {
  for (const code of [
    'monthly_history_withheld',
    'history_embedding_index_required',
    'history_keyword_retrieval_only',
    'history_embedding_unavailable',
  ])
    expect(flagText(code)).not.toBe(code);
  expect(flagDetail('monthly_history_withheld', 'Both financial and investment sharing are required for aggregate history')).toContain(
    '재무와 투자 공유',
  );
  expect(flagDetail('history_embedding_index_required')).toContain('놓칠 수 있습니다');
});
it('preserves each missing valuation scope and named item while translating its reason', () => {
  expect(
    flagDetail('net_worth_incomplete', 'Missing explicit cash coverage; Missing explicit liability coverage; 합성 계좌: Stale balance/quantity'),
  ).toBe('현금 항목을 모두 입력했는지 확인 전; 부채 항목을 모두 입력했는지 확인 전; 합성 계좌: 잔액·수량 기준일이 오래됨');
  expect(flagDetail('net_worth_incomplete', '합성 계좌(missing_fx_USD_KRW)')).toBe('합성 계좌(USD → KRW 환율 없음)');
});
