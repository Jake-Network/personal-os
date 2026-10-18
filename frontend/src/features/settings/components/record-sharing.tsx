'use client';

import { useState } from 'react';
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { notify } from '@/components/notify';
import { QueryStatus } from '@/components/query-status';
import { NativeSelect } from '@/components/ui/native-select';
import { RESOURCE_API, type Row } from '@/features/personal-data/api/resource-api';
import { recordOptions } from '@/features/personal-data/utils/record-options';

type Blocked = { local_only_records: Record<string, string[]> };
const path = '/api/settings/privacy/records';
const tables = [
  ['accounts', '계좌'],
  ['holdings', '보유자산'],
  ['liabilities', '부채'],
  ['other_assets', '기타 자산'],
  ['cashflow_entries', '현금흐름'],
  ['financial_transactions', '거래 기록'],
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
  const records = useQueries({
    queries: tables.map(([tableName]) => {
      const api = RESOURCE_API[tableName.replaceAll('_', '-')];
      const url = tableName === 'financial_transactions' ? '/api/finance/transactions' : '/api/memories';
      return {
        queryKey: api?.queryKey ?? [url],
        queryFn: () => (api ? api.list() : customInstance<Row[]>({ url })),
        enabled: tableName === table || Boolean(list.data?.local_only_records[tableName]?.length),
      };
    }),
  });
  const selected = records[tables.findIndex(([name]) => name === table)];
  const blocked = list.data?.local_only_records[table] ?? [];
  const choices = recordOptions(selected.data ?? []).filter(o => !blocked.includes(o.value));
  const save = useMutation({
    mutationFn: ({ table, id, allowed }: { table: string; id: number; allowed: boolean }) =>
      customInstance({ url: `${path}/${table}/${id}`, method: 'PUT', data: { external_allowed: allowed } }),
    onSuccess: () => {
      setId('');
      return client.invalidateQueries({ queryKey: [path] });
    },
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
          <select
            aria-label='기록 종류'
            value={table}
            onChange={e => {
              setTable(e.target.value);
              setId('');
            }}
            className='rounded border p-2'>
            {tables.map(([t, label]) => (
              <option key={t} value={t}>
                {label}
              </option>
            ))}
          </select>
          <NativeSelect
            aria-label='로컬 전용으로 변경할 기록'
            required
            value={id}
            onChange={e => setId(e.target.value)}
            disabled={selected.isPending || !!selected.error}
            className='min-w-0 max-w-full sm:w-72'>
            <option value=''>{selected.isPending ? '불러오는 중…' : choices.length ? '기록 이름으로 선택' : '공유 중인 기록이 없습니다'}</option>
            {choices.map(o => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </NativeSelect>
          <Button disabled={save.isPending || !id || !!selected.error || !list.isSuccess}>로컬 전용으로 변경</Button>
        </form>
        <QueryStatus pending={list.isPending} error={list.error} retry={list.refetch} label='공유 제외 설정' />
        <QueryStatus pending={false} error={selected.error} retry={selected.refetch} label='기록 목록' />
        {Object.entries(list.data?.local_only_records ?? {}).map(([t, ids]) => (
          <div key={t}>
            {tables.find(([key]) => key === t)?.[1] ?? t}:{' '}
            {ids.map(recordId => (
              <Button
                key={recordId}
                size='sm'
                disabled={save.isPending}
                onClick={() => save.mutate({ table: t, id: Number(recordId), allowed: true })}>
                {recordOptions(records[tables.findIndex(([name]) => name === t)]?.data ?? []).find(o => o.value === recordId)?.label ??
                  `기록 #${recordId}`}{' '}
                공유 허용
              </Button>
            ))}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
