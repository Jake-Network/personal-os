import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';

import type { HoldingsState } from './api';
import { quoteRefreshNotice, updateQuoteCaches } from './use-quote-refresh';

const state = (values: Partial<HoldingsState>) => ({ warning: null, ...values }) as HoldingsState;

describe('quote refresh feedback', () => {
  it('keeps cooldown and prior failures visible instead of claiming fresh prices', () => {
    const notice = quoteRefreshNotice(
      state({
        refresh_state: 'cooldown',
        refresh_after_seconds: 121,
        warning: '조회 간격 제한으로 121초 후 다시 조회하세요. 이전 조회에 실패했습니다.',
      }),
    );
    expect(notice.variant).toBe('warning');
    expect(notice.message).toContain('121초 후');
    expect(notice.message).toContain('이전 조회에 실패했습니다.');
    expect(notice.message).not.toContain('갱신했습니다');
    expect(notice.message.match(/121초/g)).toHaveLength(1);
    expect(quoteRefreshNotice(state({ refresh_state: 'cooldown', refresh_after_seconds: 121 })).message).toContain('121초 후');
  });

  it('distinguishes waiting, disconnected, failed and updated outcomes', () => {
    expect(quoteRefreshNotice(state({ refresh_state: 'waiting' })).message).toContain('가격 반영을 기다리고');
    expect(quoteRefreshNotice(state({ refresh_state: 'not_connected' })).message).toContain('연결이 필요');
    expect(quoteRefreshNotice(state({ refresh_state: 'failed', warning: 'Google 연결을 확인하세요.' })).message).toContain('갱신하지 못했습니다');
    expect(quoteRefreshNotice(state({ refresh_state: 'updated' })).variant).toBe('success');
    expect(quoteRefreshNotice(state({ refresh_state: 'updated', warning: '일부 종목은 시세 대기 중입니다.' })).variant).toBe('warning');
    expect(quoteRefreshNotice(state({})).variant).toBe('info');
  });
});

describe('quote refresh caches', () => {
  it('replaces holdings and invalidates portfolio, dashboard and connection status together', async () => {
    const client = new QueryClient();
    const keys = [['finance', 'portfolio'], getSummaryQueryKey(), ['market-data'], ['/api/market-data/status']];
    for (const key of keys) client.setQueryData(key, { previous: true });
    const refreshed = state({ refresh_state: 'updated', rows: [] });
    await updateQuoteCaches(client, refreshed);
    expect(client.getQueryData(['finance', 'holdings'])).toEqual(refreshed);
    for (const key of keys) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    client.clear();
  });
});
