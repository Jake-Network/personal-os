'use client';

import { useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import { Check, Plus, Trash2 } from 'lucide-react';

import {
  getCashflowCategoryRulesQueryKey,
  getRecurringCashflowsQueryKey,
  getRecurringDueQueryKey,
  useCashflowCategoryRules,
  useCreateCashflowCategoryRule,
  useCreateRecurringCashflow,
  useDeleteCashflowCategoryRule,
  useDeleteRecurringCashflow,
  useRecordRecurringCashflow,
  useRecurringCashflows,
  useRecurringDue,
} from '@/api-client/generated/portfolio/portfolio';
import type { CashflowCategoryRuleCreate, RecurringCashflowCreate } from '@/api-client/model';
import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Button } from '@/components/ui/button';
import { DataForm } from '@/features/personal-data/components/data-form';
import { useSchemaFields } from '@/features/personal-data/hooks/use-schema-fields';
import { dateOnly } from '@/lib/utils/format';
import { todayKey } from '@/lib/utils/zoned';

import { CASHFLOW_CATEGORIES } from './cashflow-categories';
import { money } from './presentation';

const RECURRING_LABELS = {
  name: '이름',
  kind: '수입·지출',
  amount: '금액 (원)',
  category: '분류',
  day_of_month: '매월 며칠',
  start_on: '시작일',
  end_on: '종료일',
  active: '사용',
};
const KIND_LABELS = { income: '수입', expense: '지출', equals: '적요가 같을 때', contains: '적요에 포함될 때' };

function useInvalidateLedger() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ['finance'] }),
      client.invalidateQueries({ queryKey: ['/api/finance/cashflow'] }),
      client.invalidateQueries({ queryKey: ['/api/dashboard/summary'] }),
      client.invalidateQueries({ queryKey: getRecurringDueQueryKey() }),
      client.invalidateQueries({ queryKey: getRecurringCashflowsQueryKey() }),
    ]);
}

/** This month's recurring items. Each is recorded only when the user presses 기록. */
export function RecurringDueList({ compact = false }: { compact?: boolean }) {
  const due = useRecurringDue();
  const record = useRecordRecurringCashflow();
  const invalidate = useInvalidateLedger();
  const today = todayKey();
  const rows = due.data ?? [];
  if (compact && !rows.some(r => !r.recorded)) return null;
  return (
    <>
      <QueryStatus pending={due.isPending} error={due.error} retry={due.refetch} label='반복 거래' />
      {rows.length === 0 && !due.isPending ? (
        <EmptyState className='py-4'>이번 달 반복 거래가 없습니다.</EmptyState>
      ) : (
        <ul className='divide-y'>
          {rows
            .filter(r => !compact || !r.recorded)
            .map(r => (
              <li key={r.recurring_id} className='flex flex-wrap items-center gap-2 py-2 text-ui'>
                <span className='w-14 shrink-0 text-xs text-faint'>{dateOnly(r.scheduled_on).replace(/^\d+\.\s*/, '')}</span>
                <span className='min-w-0 flex-1 truncate'>{r.name}</span>
                <span className={`tabular-nums ${r.kind === 'income' ? 'text-success' : ''}`}>
                  {r.kind === 'income' ? '+' : '-'}
                  {money(r.amount, r.currency)}
                </span>
                {r.recorded ? (
                  <span className='flex items-center gap-1 text-xs text-success'>
                    <Check className='size-3.5' aria-hidden /> 기록함
                  </span>
                ) : r.scheduled_on > today ? (
                  // The server records only after the scheduled day, so the ledger never holds money that has not moved.
                  <span className='text-xs text-faint'>예정</span>
                ) : (
                  <Button
                    size='sm'
                    variant='primary'
                    disabled={record.isPending}
                    onClick={() =>
                      record.mutate(
                        { itemId: r.recurring_id, data: { month: r.month } },
                        {
                          onSuccess: async () => {
                            notify.success(`${r.name}을(를) 장부에 기록했습니다`);
                            await invalidate();
                          },
                          onError: notify.error,
                        },
                      )
                    }>
                    기록
                  </Button>
                )}
              </li>
            ))}
        </ul>
      )}
    </>
  );
}

/** Recurring schedules and description → category rules, managed next to the ledger. */
export function RecurringAndRules() {
  const items = useRecurringCashflows();
  const create = useCreateRecurringCashflow();
  const remove = useDeleteRecurringCashflow();
  const rules = useCashflowCategoryRules();
  const createRule = useCreateCashflowCategoryRule();
  const removeRule = useDeleteCashflowCategoryRule();
  const recurringFields = useSchemaFields('/api/finance/recurring');
  const ruleFields = useSchemaFields('/api/finance/cashflow/category-rules');
  const client = useQueryClient();
  const invalidate = useInvalidateLedger();
  const [adding, setAdding] = useState(false);
  const [addingRule, setAddingRule] = useState(false);

  return (
    <>
      <Section
        title='이번 달 반복 거래'
        info={<p>월세·급여·구독료처럼 매달 반복되는 거래입니다. 자동으로 장부에 넣지 않으며, 실제로 나가거나 들어온 뒤 기록을 누르세요. 짧은 달에는 말일에 표시합니다.</p>}
        actions={
          <Button size='sm' onClick={() => setAdding(v => !v)}>
            <Plus /> 반복 거래 추가
          </Button>
        }>
        {adding && recurringFields.data && (
          <div className='mb-3 rounded-md border p-3'>
            <DataForm
              fields={recurringFields.data}
              labels={RECURRING_LABELS}
              enumLabels={KIND_LABELS}
              current={{ start_on: todayKey(), active: true }}
              suggestions={{ category: { dependsOn: 'kind', options: CASHFLOW_CATEGORIES } }}
              submitLabel='저장'
              onCancel={() => setAdding(false)}
              onSubmit={async payload => {
                await create.mutateAsync({ data: payload as unknown as RecurringCashflowCreate }, { onError: notify.error });
                setAdding(false);
                await invalidate();
              }}
            />
          </div>
        )}
        <RecurringDueList />
        {(items.data?.length ?? 0) > 0 && (
          <details className='mt-3 text-ui'>
            <summary className='cursor-pointer text-xs text-muted-foreground'>반복 거래 {items.data!.length}개 관리</summary>
            <ul className='mt-2 divide-y'>
              {items.data!.map(item => (
                <li key={item.id} className='flex items-center gap-2 py-1.5'>
                  <span className='flex-1 truncate'>
                    {item.name} · 매월 {item.day_of_month}일 · {money(item.amount, item.currency)}
                    {!item.active && <span className='text-faint'> (사용 안 함)</span>}
                  </span>
                  <Button
                    variant='ghost'
                    size='icon-sm'
                    aria-label={`${item.name} 삭제`}
                    onClick={() => remove.mutate({ itemId: item.id }, { onSuccess: () => void invalidate(), onError: notify.error })}>
                    <Trash2 />
                  </Button>
                </li>
              ))}
            </ul>
            <p className='mt-1 text-xs text-faint'>삭제해도 이미 장부에 기록한 거래는 남습니다.</p>
          </details>
        )}
      </Section>

      <Section
        title='자동 분류 규칙'
        info={<p>가져오기 미리보기에서 분류가 비어 있는 행에 규칙의 분류를 제안합니다. 이미 저장한 기록의 분류는 바꾸지 않습니다.</p>}
        actions={
          <Button size='sm' onClick={() => setAddingRule(v => !v)}>
            <Plus /> 규칙 추가
          </Button>
        }>
        {addingRule && ruleFields.data && (
          <div className='mb-3 rounded-md border p-3'>
            <DataForm
              fields={ruleFields.data}
              labels={{ match_text: '적요 문구', match_kind: '조건', category: '분류' }}
              enumLabels={KIND_LABELS}
              suggestions={{ category: Object.values(CASHFLOW_CATEGORIES).flat() }}
              submitLabel='저장'
              onCancel={() => setAddingRule(false)}
              onSubmit={async payload => {
                await createRule.mutateAsync({ data: payload as unknown as CashflowCategoryRuleCreate }, { onError: notify.error });
                setAddingRule(false);
                await client.invalidateQueries({ queryKey: getCashflowCategoryRulesQueryKey() });
              }}
            />
          </div>
        )}
        <QueryStatus pending={rules.isPending} error={rules.error} retry={rules.refetch} label='분류 규칙' />
        {rules.data?.length === 0 ? (
          <EmptyState className='py-4'>규칙이 없습니다. 가져오기 미리보기에서 분류를 고치고 ‘규칙’을 체크하면 저장됩니다.</EmptyState>
        ) : (
          <ul className='divide-y'>
            {rules.data?.map(rule => (
              <li key={rule.id} className='flex items-center gap-2 py-1.5 text-ui'>
                <span className='flex-1 truncate'>
                  <span className='text-faint'>{rule.match_kind === 'equals' ? '적요 =' : '적요에'}</span> {rule.match_text}
                  {rule.match_kind === 'contains' && <span className='text-faint'> 포함</span>} → <strong>{rule.category}</strong>
                </span>
                <Button
                  variant='ghost'
                  size='icon-sm'
                  aria-label={`${rule.match_text} 규칙 삭제`}
                  onClick={() =>
                    removeRule.mutate(
                      { ruleId: rule.id },
                      { onSuccess: () => void client.invalidateQueries({ queryKey: getCashflowCategoryRulesQueryKey() }), onError: notify.error },
                    )
                  }>
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}
