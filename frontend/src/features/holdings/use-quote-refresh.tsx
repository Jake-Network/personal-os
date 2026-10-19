'use client';

import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';

import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';
import { Alert } from '@/components/ui/alert';

import { holdingsApi, type HoldingsState } from './api';

export function quoteRefreshNotice(data: HoldingsState): { variant: 'success' | 'warning' | 'info'; message: string } {
  const delay = data.refresh_after_seconds;
  const wait = delay != null && delay > 0 ? `${Math.ceil(delay)}초 후 다시 갱신할 수 있습니다.` : '잠시 후 다시 갱신해 주세요.';
  switch (data.refresh_state) {
    case 'cooldown':
      return { variant: 'warning', message: data.warning || `아직 갱신 대기 시간입니다. ${wait}` };
    case 'waiting':
      return { variant: 'warning', message: `시세 제공처의 가격 반영을 기다리고 있습니다. ${wait}${data.warning ? ` ${data.warning}` : ''}` };
    case 'not_connected':
      return { variant: 'warning', message: data.warning || '자동 시세 연결이 필요합니다. 시세 연결 설정을 확인해 주세요.' };
    case 'failed':
      return { variant: 'warning', message: `시세를 갱신하지 못했습니다. ${data.warning || '연결 상태를 확인하고 다시 시도해 주세요.'}` };
    case 'updated':
      return { variant: data.warning ? 'warning' : 'success', message: `시세를 갱신했습니다.${data.warning ? ` ${data.warning}` : ''}` };
    default:
      return { variant: data.warning ? 'warning' : 'info', message: data.warning || '시세 조회 결과를 확인했습니다.' };
  }
}

export async function updateQuoteCaches(client: QueryClient, data: HoldingsState) {
  client.setQueryData(['finance', 'holdings'], data);
  await Promise.all([
    client.invalidateQueries({ queryKey: ['finance', 'portfolio'] }),
    client.invalidateQueries({ queryKey: getSummaryQueryKey() }),
    client.invalidateQueries({ queryKey: ['market-data'] }),
    client.invalidateQueries({ queryKey: ['/api/market-data/status'] }),
  ]);
}

export function useQuoteRefresh() {
  const client = useQueryClient();
  return useMutation({ mutationFn: holdingsApi.refresh, onSuccess: data => updateQuoteCaches(client, data) });
}

export function QuoteRefreshNotice({ refresh }: { refresh: ReturnType<typeof useQuoteRefresh> }) {
  if (refresh.isPending) return <Alert className='mb-3'>시세를 확인하고 있습니다…</Alert>;
  if (refresh.error)
    return (
      <Alert variant='destructive' className='mb-3'>
        시세를 갱신하지 못했습니다. {refresh.error.message}
      </Alert>
    );
  if (!refresh.data) return null;
  const notice = quoteRefreshNotice(refresh.data);
  return (
    <Alert variant={notice.variant} className='mb-3'>
      {notice.message}
    </Alert>
  );
}
