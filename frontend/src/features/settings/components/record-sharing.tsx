'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { notify } from '@/components/notify';

type Blocked = { local_only_records: Record<string, string[]> };
const path = '/api/settings/privacy/records';
const tables = [
  ['accounts', '계좌'],
  ['holdings', '보유자산'],
  ['liabilities', '부채'],
  ['other_assets', '기타 자산'],
  ['cashflow_entries', '현금흐름'],
  ['job_applications', '채용 지원'],
  ['calendar_events', '일정'],
  ['goals', '목표'],
  ['personal_memories', '기억'],
] as const;

export function RecordSharing() {
  const client = useQueryClient();
  const [table, setTable] = useState<string>('accounts');
  const [id, setId] = useState('');
  const list = useQuery({ queryKey: [path], queryFn: () => customInstance<Blocked>({ url: path }) });
  const save = useMutation({
    mutationFn: ({ table, id, allowed }: { table: string; id: number; allowed: boolean }) =>
      customInstance({ url: `${path}/${table}/${id}`, method: 'PUT', data: { external_allowed: allowed } }),
    onSuccess: () => client.invalidateQueries({ queryKey: [path] }),
    onError: notify.error,
  });
  return (
    <Card className='mt-4'>
      <CardHeader>
        <CardTitle>개별 기록 로컬 전용 설정</CardTitle>
      </CardHeader>
      <CardContent className='space-y-3'>
        <p className='text-sm'>
          로컬 화면에서는 계속 볼 수 있습니다. 계산에 포함된 기록을 제외하면 해당 합계 전체를 상담에서 생략하고 불완전성을 표시합니다. 기존 대화와
          파생 자료도 전송 전에 재검사합니다.
        </p>
        <form
          className='flex flex-wrap gap-2'
          onSubmit={e => {
            e.preventDefault();
            save.mutate({ table, id: Number(id), allowed: false });
          }}>
          <select aria-label='기록 종류' value={table} onChange={e => setTable(e.target.value)} className='rounded border p-2'>
            {tables.map(([t, label]) => (
              <option key={t} value={t}>
                {label}
              </option>
            ))}
          </select>
          <input
            aria-label='기록 ID'
            placeholder='기록 ID'
            min='1'
            required
            type='number'
            value={id}
            onChange={e => setId(e.target.value)}
            className='w-28 rounded border p-2'
          />
          <Button disabled={save.isPending || !id}>로컬 전용으로 변경</Button>
        </form>
        {list.error && <p role='alert'>{list.error.message}</p>}
        {Object.entries(list.data?.local_only_records ?? {}).map(([t, ids]) => (
          <div key={t}>
            {tables.find(([key]) => key === t)?.[1] ?? t}:{' '}
            {ids.map(recordId => (
              <Button
                key={recordId}
                size='sm'
                disabled={save.isPending}
                onClick={() => save.mutate({ table: t, id: Number(recordId), allowed: true })}>
                #{recordId} 공유 허용
              </Button>
            ))}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
