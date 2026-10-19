'use client';

import { useState } from 'react';
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import { Button } from '@/components/ui/button';
import { Section } from '@/components/page-container';
import { notify } from '@/components/notify';
import { QueryStatus } from '@/components/query-status';
import { NativeSelect } from '@/components/ui/native-select';
import { RESOURCE_API, type Row } from '@/features/personal-data/api/resource-api';
import { recordOptions } from '@/features/personal-data/utils/record-options';

type Blocked = { local_only_records: Record<string, string[]> };
const path = '/api/settings/privacy/records';
const tables = [
  ['accounts', '계좌'],
  ['holdings', '보유 종목'],
  ['liabilities', '부채'],
  ['other_assets', '기타 자산'],
  ['cashflow_entries', '수입·지출'],
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
  const label = (t: string, recordId: string) =>
    (recordOptions(records[tables.findIndex(([name]) => name === t)]?.data ?? []).find(o => o.value === recordId)?.label ?? '찾을 수 없는 기록').replace(/ \(#\d+\)$/, '');
  const blockedEntries = Object.entries(list.data?.local_only_records ?? {}).filter(([, ids]) => ids.length > 0);

  return (
    <Section
      title='이 기기에서만 쓸 기록'
      info={<p>합계에 들어가는 기록을 빼면 그 합계 전체를 상담에서 생략하고 불완전하다고 표시합니다. 기존 대화와 파생 자료도 보내기 전에 다시 검사합니다.</p>}>
      <p className='py-1 text-ui text-muted-foreground'>영역은 공유하더라도 특정 기록만 AI에 보내지 않을 수 있습니다. 화면에서는 계속 보입니다.</p>
      <form
        className='flex flex-wrap gap-2 py-2'
        onSubmit={e => {
          e.preventDefault();
          save.mutate({ table, id: Number(id), allowed: false });
        }}>
        <NativeSelect
          aria-label='기록 종류'
          className='w-auto'
          value={table}
          onChange={e => {
            setTable(e.target.value);
            setId('');
          }}>
          {tables.map(([t, l]) => (
            <option key={t} value={t}>
              {l}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          aria-label='이 기기에서만 쓸 기록'
          required
          value={id}
          onChange={e => setId(e.target.value)}
          disabled={selected.isPending || !!selected.error}
          className='min-w-0 max-w-full sm:w-72'>
          <option value=''>{selected.isPending ? '불러오는 중…' : choices.length ? '기록 선택' : '공유 중인 기록이 없습니다'}</option>
          {choices.map(o => (
            <option key={o.value} value={o.value}>
              {o.label.replace(/ \(#\d+\)$/, '')}
            </option>
          ))}
        </NativeSelect>
        <Button disabled={save.isPending || !id || !!selected.error || !list.isSuccess}>보내지 않기</Button>
      </form>
      <QueryStatus pending={list.isPending} error={list.error} retry={list.refetch} label='공유 제외 설정' rows={2} />
      <QueryStatus pending={false} error={selected.error} retry={selected.refetch} label='기록 목록' />
      {list.data && blockedEntries.length === 0 && <p className='py-2 text-xs text-faint'>따로 제외한 기록이 없습니다.</p>}
      <ul className='divide-y'>
        {blockedEntries.flatMap(([t, ids]) =>
          ids.map(recordId => (
            <li key={`${t}:${recordId}`} className='flex items-center gap-2 py-2'>
              <span className='w-20 shrink-0 text-xs text-muted-foreground'>{tables.find(([key]) => key === t)?.[1] ?? '기록'}</span>
              <span className='min-w-0 flex-1'>{label(t, recordId)}</span>
              <Button size='sm' disabled={save.isPending} onClick={() => save.mutate({ table: t, id: Number(recordId), allowed: true })}>
                다시 공유
              </Button>
            </li>
          )),
        )}
      </ul>
    </Section>
  );
}
