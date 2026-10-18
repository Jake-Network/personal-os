'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import { Button } from '@/components/ui/button';
import { Alert } from '@/components/ui/alert';
import { notify } from '@/components/notify';

type MarketStatus = { configured: boolean; last_error: string | null; last_success_at: string | null };
type ImportPreview = {
  import_id: number;
  rows: { row: Record<string, unknown>; issues: string[]; existing_position_id: string | null }[];
  preserved_history: boolean;
};

export function MarketConnection() {
  const client = useQueryClient();
  const [importId, setImportId] = useState('');
  const state = useQuery({ queryKey: ['market-data'], queryFn: () => customInstance<MarketStatus>({ url: '/api/market-data/status' }) });
  const preview = useMutation({
    mutationFn: () => customInstance<ImportPreview>({ url: `/api/market-data/imports/${Number(importId)}/preview` }),
    onError: notify.error,
  });
  const action = useMutation({
    mutationFn: (operation: 'initialize' | 'refresh' | 'import') =>
      customInstance<{ warning?: string }>({
        url: operation === 'import' ? `/api/market-data/imports/${Number(importId)}` : `/api/market-data/${operation}`,
        method: 'POST',
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ['market-data'] }),
        client.invalidateQueries({ queryKey: ['finance'] }),
        client.invalidateQueries({ queryKey: ['/api/finance/holdings'] }),
      ]),
    onError: notify.error,
  });
  return (
    <div className='space-y-3'>
      <div className='flex flex-wrap gap-2'>
        <Button disabled={action.isPending || state.isPending || !!state.data?.configured} onClick={() => action.mutate('initialize')}>
          시세 전용 파일 새로 만들기
        </Button>
        <Button disabled={action.isPending || !state.data?.configured} onClick={() => action.mutate('refresh')}>
          시세 갱신
        </Button>
      </div>
      <p className='text-xs text-faint'>
        갱신은 5분 제한을 공통 적용합니다. 이전의 광범위한 Google 승인은 Google 계정에서 해제한 뒤 다시 연결하세요.
      </p>
      {state.data?.last_error && <Alert variant='warning'>{state.data.last_error}</Alert>}
      {state.error && <Alert variant='destructive'>{state.error.message}</Alert>}
      {action.data?.warning && <Alert variant='warning'>{action.data.warning}</Alert>}
      <details>
        <summary>기존 Sheets 저장 자료를 로컬로 편입</summary>
        <p className='my-2 text-sm'>이미 보존된 import ID를 입력하세요. 원격 파일은 변경하지 않습니다. 같은 티커의 다른 계좌 행을 합치지 않습니다.</p>
        <form
          onSubmit={e => {
            e.preventDefault();
            preview.mutate();
          }}
          className='flex gap-2'>
          <input
            aria-label='기존 import ID'
            type='number'
            min='1'
            value={importId}
            onChange={e => {
              setImportId(e.target.value);
              preview.reset();
            }}
            className='rounded border p-2'
          />
          <Button disabled={!importId || preview.isPending} type='submit'>
            이전 미리보기
          </Button>
        </form>
        {preview.data && (
          <>
            <ul className='my-3'>
              {preview.data.rows.map((r, i) => (
                <li key={i} className='border-b py-2'>
                  {String(r.row.label ?? r.row.id ?? i)} · {String(r.row.ticker ?? '')} · 수량 {String(r.row.quantity ?? '미확인')} ·{' '}
                  {r.existing_position_id ? '이미 편입됨' : '새 항목'} {r.issues.join(' · ')}
                </li>
              ))}
            </ul>
            <Button disabled={action.isPending || preview.data.rows.some(r => r.issues.length > 0)} onClick={() => action.mutate('import')}>
              미리보기 확인 · 로컬 편입
            </Button>
          </>
        )}
      </details>
    </div>
  );
}
