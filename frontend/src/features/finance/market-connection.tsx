'use client';

import { useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { customInstance } from '@/api-client/custom-client';
import { notify } from '@/components/notify';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { relative } from '@/lib/utils/format';

export type MarketStatus = {
  configured: boolean;
  account_matches: boolean;
  current_account_key: string;
  spreadsheet_id: string | null;
  last_error: string | null;
  last_success_at: string | null;
};
type ImportPreview = {
  import_id: number;
  rows: { row: Record<string, unknown>; issues: string[]; existing_position_id: string | null }[];
  preserved_history: boolean;
};

export function useMarketStatus() {
  return useQuery({ queryKey: ['market-data'], queryFn: () => customInstance<MarketStatus>({ url: '/api/market-data/status' }) });
}

function useMarketInvalidate() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ['market-data'] }),
      client.invalidateQueries({ queryKey: ['finance'] }),
      client.invalidateQueries({ queryKey: ['/api/finance/holdings'] }),
    ]);
}

/** The quote-only Google file: create it, reconnect it to the current account, refresh quotes. */
export function MarketConnection() {
  const state = useMarketStatus();
  const invalidate = useMarketInvalidate();
  const action = useMutation({
    mutationFn: (operation: 'initialize' | 'replace' | 'refresh') =>
      customInstance<{ warning?: string }>({
        url: `/api/market-data/${operation}`,
        method: 'POST',
        data:
          operation === 'replace'
            ? {
                expected_spreadsheet_id: state.data?.spreadsheet_id,
                expected_account_key: state.data?.current_account_key,
              }
            : undefined,
      }),
    onSuccess: invalidate,
    onError: notify.error,
  });
  const data = state.data;
  return (
    <div className='flex flex-col gap-3'>
      <p className='text-ui'>
        {state.isPending
          ? '시세 파일 상태를 확인하는 중…'
          : !data?.configured
            ? '시세 파일이 아직 없습니다.'
            : `시세 파일 연결됨 · 최근 갱신 ${relative(data.last_success_at, '없음')}`}
      </p>
      <div className='flex flex-wrap gap-2'>
        {!data?.configured ? (
          <Button variant='primary' disabled={action.isPending || state.isPending} onClick={() => action.mutate('initialize')}>
            시세 파일 만들기
          </Button>
        ) : (
          <>
            <Button disabled={action.isPending || !data.account_matches} onClick={() => action.mutate('refresh')}>
              시세 갱신
            </Button>
            <Button variant='ghost' disabled={action.isPending || state.isFetching} onClick={() => action.mutate('replace')}>
              현재 계정으로 새 시세 파일 연결
            </Button>
          </>
        )}
      </div>
      {data?.configured && !data.account_matches && (
        <Alert variant='warning'>연결된 Google 계정이 기존 시세 파일과 다릅니다. 현재 계정으로 새 시세 파일을 연결하세요.</Alert>
      )}
      {data?.last_error && <Alert variant='warning'>{data.last_error}</Alert>}
      {state.error && <Alert variant='destructive'>{state.error.message}</Alert>}
      {action.data?.warning && <Alert variant='warning'>{action.data.warning}</Alert>}
    </div>
  );
}

/** Bring holdings preserved from the old Sheets setup into local records, after a preview. */
export function LegacySheetsImport() {
  const invalidate = useMarketInvalidate();
  const [importId, setImportId] = useState('');
  const preview = useMutation({
    mutationFn: () => customInstance<ImportPreview>({ url: `/api/market-data/imports/${Number(importId)}/preview` }),
    onError: notify.error,
  });
  const commit = useMutation({
    mutationFn: () => customInstance({ url: `/api/market-data/imports/${Number(importId)}`, method: 'POST' }),
    onSuccess: () => {
      notify.success('로컬 기록으로 옮겼습니다');
      preview.reset();
      return invalidate();
    },
    onError: notify.error,
  });
  return (
    <div className='flex flex-col gap-3'>
      <form
        onSubmit={e => {
          e.preventDefault();
          preview.mutate();
        }}
        className='flex flex-wrap items-end gap-2'>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='legacy-import'>가져오기 번호</Label>
          <Input
            id='legacy-import'
            type='number'
            min='1'
            className='w-40'
            value={importId}
            onChange={e => {
              setImportId(e.target.value);
              preview.reset();
            }}
          />
        </div>
        <Button disabled={!importId || preview.isPending} type='submit'>
          미리보기
        </Button>
      </form>
      {preview.data && (
        <>
          <ul className='divide-y rounded-lg border'>
            {preview.data.rows.map((r, i) => (
              <li key={i} className='flex flex-wrap items-baseline gap-x-2 px-3 py-2 text-ui'>
                <span className='font-medium'>{String(r.row.label ?? r.row.ticker ?? `항목 ${i + 1}`)}</span>
                <span className='text-xs text-faint'>
                  {String(r.row.ticker ?? '')} · 수량 {String(r.row.quantity ?? '미확인')}
                </span>
                <span className='ml-auto text-xs'>{r.existing_position_id ? '이미 옮김' : '새 항목'}</span>
                {r.issues.length > 0 && <span className='basis-full text-xs text-destructive'>{r.issues.join(' · ')}</span>}
              </li>
            ))}
          </ul>
          <div>
            <Button variant='primary' disabled={commit.isPending || preview.data.rows.some(r => r.issues.length > 0)} onClick={() => commit.mutate()}>
              확인하고 로컬로 옮기기
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
