'use client';

import { useQuery } from '@tanstack/react-query';
import type { ComponentProps } from 'react';
import { customInstance } from '@/api-client/custom-client';
import { QueryStatus } from '@/components/query-status';
import { NativeSelect } from '@/components/ui/native-select';
import { RESOURCE_API, type Row } from '../api/resource-api';
import { recordOptions, type RecordOption } from '../utils/record-options';
import { getListDecisionsQueryKey, listDecisions } from '@/api-client/generated/memory/memory';

const RELATIONS: Record<string, string> = {
  account_id: 'accounts',
  counterparty_account_id: 'accounts',
  holding_id: 'holdings',
  application_id: 'job-applications',
  goal_id: 'goals',
  reverses_id: 'transactions',
  project_id: 'career-projects',
  decision_id: 'decisions',
};

export function hasRecordChoices(name: string) {
  return name in RELATIONS;
}

function recordQuery(resource: string) {
  const api = RESOURCE_API[resource];
  if (api) return { queryKey: api.queryKey, queryFn: api.list };
  if (resource === 'decisions')
    return {
      queryKey: getListDecisionsQueryKey(),
      queryFn: async (): Promise<Row[]> => (await listDecisions()).map(row => ({ ...row })),
    };
  if (resource === 'career-projects')
    return {
      queryKey: ['career-records', 'projects'],
      queryFn: () => customInstance<Row[]>({ url: '/api/career/records', params: { kind: 'project' } }),
    };
  return {
    queryKey: ['finance', 'transactions', 'all'],
    queryFn: () => customInstance<Row[]>({ url: '/api/finance/transactions' }),
  };
}

export function RecordSelect({
  fieldName,
  options,
  ...props
}: ComponentProps<typeof NativeSelect> & {
  fieldName: string;
  options?: RecordOption[];
}) {
  const resource = RELATIONS[fieldName];
  const query = useQuery({
    ...recordQuery(resource),
    enabled: options === undefined,
  });
  const choices = options ?? recordOptions(query.data ?? []);
  const value = props.value ?? props.defaultValue;
  const missing = value != null && value !== '' && !choices.some(o => o.value === String(value));
  return (
    <>
      <NativeSelect {...props}>
        <option value='' disabled={props.required}>
          {query.isPending && options === undefined ? '불러오는 중…' : props.required ? '선택하세요' : '연결 안 함'}
        </option>
        {missing && <option value={String(value)}>현재 연결 기록 (#{String(value)})</option>}
        {choices.map(o => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </NativeSelect>
      {options === undefined && <QueryStatus pending={false} error={query.error} retry={query.refetch} label='연결할 기록' />}
      {options === undefined && query.isSuccess && !choices.length && (
        <p className='text-xs text-muted-foreground'>연결할 기록이 없습니다. 먼저 해당 기록을 추가하세요.</p>
      )}
    </>
  );
}
