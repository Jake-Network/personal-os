'use client';

import { type ReactNode, useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, RefreshCw } from 'lucide-react';

import { toApiError } from '@/api-client/api-error';
import { todayKey } from '@/lib/utils/zoned';
import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';
import { customInstance } from '@/api-client/custom-client';
import { useConfirm } from '@/components/confirm-dialog';
import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { dateOnly, relative } from '@/lib/utils/format';
import { cn } from '@/lib/utils';

import type { Row } from '@/features/personal-data/api/resource-api';
import { RecordSheet } from '@/features/personal-data/components/record-sheet';
import { enumLabel } from '@/features/personal-data/consts/resources';
import { useResourceRows, useInvalidateResource } from '@/features/personal-data/hooks/use-resource';
import { useRecordParam } from '@/features/personal-data/hooks/use-record-param';

import { type FinanceLine, financeApi } from './api';
import { AccountValuationStatus, Spendability } from './account-valuation';
import { BalanceCheckInSheet } from './balance-check-in';
import { money } from './presentation';

interface ListConfig {
  resource: 'accounts' | 'liabilities' | 'other-assets';
  /** Valuation line kind for the same record. */
  kind: 'cash' | 'liability' | 'other';
  title: string;
  addLabel: string;
  empty: string;
  amountField: 'balance' | 'value';
  asOfField: 'balance_as_of' | 'value_as_of';
  detail: (row: Row) => string;
  extra?: { heading: string; cell: (line?: FinanceLine) => ReactNode };
  info?: ReactNode;
}

const LISTS: ListConfig[] = [
  {
    resource: 'accounts',
    kind: 'cash',
    title: '계좌',
    addLabel: '계좌 추가',
    empty: '입출금·예금·증권 예수금 계좌를 기록하면 순자산과 생활비 현금을 계산합니다.',
    amountField: 'balance',
    asOfField: 'balance_as_of',
    detail: row => [row.institution, enumLabel(row.kind)].filter(Boolean).join(' · '),
    extra: {
      heading: '생활비',
      cell: line => <Spendability spendable={line?.spendable} />,
    },
    info: '"생활비로 사용 가능"을 켠 현금성 계좌만 생활비 현금과 버틸 기간 계산에 들어갑니다.',
  },
  {
    resource: 'liabilities',
    kind: 'liability',
    title: '부채',
    addLabel: '부채 추가',
    empty: '대출이나 카드 잔액을 기록하세요. 부채가 없다면 아래에서 입력 완료를 확인하세요.',
    amountField: 'balance',
    asOfField: 'balance_as_of',
    detail: row =>
      [
        enumLabel(row.kind),
        row.interest_rate ? `금리 ${row.interest_rate}%` : null,
        row.monthly_payment ? `월 ${money(row.monthly_payment as string, (row.currency as string) ?? 'KRW')}` : null,
      ]
        .filter(Boolean)
        .join(' · '),
  },
  {
    resource: 'other-assets',
    kind: 'other',
    title: '기타 자산',
    addLabel: '기타 자산 추가',
    empty: '부동산·차량·예상 퇴직금 등 계좌 밖의 자산을 기록합니다.',
    amountField: 'value',
    asOfField: 'value_as_of',
    detail: row => enumLabel(row.kind),
    info: '기타 자산은 순자산에는 들어가지만 생활비 현금에는 들어가지 않습니다.',
  },
];

export function RecordList({
  config,
  lines,
  pending,
  failed,
  selected,
  onSelect,
}: {
  config: ListConfig;
  lines: FinanceLine[];
  pending: boolean;
  failed: boolean;
  selected: number | null;
  onSelect: (id: number | null) => void;
}) {
  const rows = useResourceRows(config.resource);
  const invalidate = useInvalidateResource();
  const confirmValue = useMutation({
    mutationFn: (row: Row) => financeApi.confirmValue(config.resource, row.id, String(row.version)),
    onSuccess: () => notify.success('오늘 기준으로 확인했습니다'),
    onError: error => notify.error(toApiError(error).status === 409 ? '다른 화면에서 값이 변경됐습니다. 최신 값을 다시 확인하세요.' : error),
    onSettled: () => invalidate(config.resource),
  });
  const [creating, setCreating] = useState(false);
  const editing = selected === null ? null : (rows.data?.find(r => r.id === selected) ?? null);
  const lineOf = (row: Row) => lines.find(l => l.kind === config.kind && l.id === String(row.id));

  return (
    <Section
      title={config.title}
      count={rows.data?.length}
      info={config.info}
      actions={
        <Button size='sm' onClick={() => setCreating(true)}>
          <Plus /> {config.addLabel}
        </Button>
      }>
      <QueryStatus pending={rows.isPending} error={rows.error} retry={rows.refetch} label={config.title} rows={2} />
      {rows.data?.length === 0 && (
        <>
          <EmptyState className='py-5'>{config.empty}</EmptyState>
          {config.resource === 'liabilities' && <CoverageConfirm onlyDebt />}
        </>
      )}
      {rows.data && rows.data.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>이름</TableHead>
              <TableHead className='text-right'>{config.amountField === 'value' ? '평가액' : '잔액'}</TableHead>
              <TableHead className='hidden md:table-cell'>기준일</TableHead>
              {config.extra && <TableHead className='hidden md:table-cell'>{config.extra.heading}</TableHead>}
              <TableHead>상태</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.data.map(row => {
              const line = lineOf(row);
              const asOf = row[config.asOfField] as string | null;
              return (
                <TableRow key={row.id} className='cursor-pointer' onClick={() => onSelect(row.id)}>
                  <TableCell>
                    <button type='button' className='text-left font-medium hover:underline' onClick={() => onSelect(row.id)}>
                      {String(row.name)}
                    </button>
                    <span className='block text-xs text-faint'>{config.detail(row)}</span>
                  </TableCell>
                  <TableCell className={cn('text-right tabular-nums', config.kind === 'liability' && 'text-destructive')}>
                    {money(row[config.amountField] as string, (row.currency as string) ?? 'KRW')}
                  </TableCell>
                  <TableCell className='hidden md:table-cell'>
                    {asOf ? (
                      <>
                        {dateOnly(asOf)}
                        <span className='block text-xs text-faint'>{relative(asOf)}</span>
                      </>
                    ) : (
                      '미기록'
                    )}
                  </TableCell>
                  {config.extra && <TableCell className='hidden md:table-cell'>{config.extra.cell(pending || failed ? undefined : line)}</TableCell>}
                  <TableCell onClick={e => e.stopPropagation()}>
                    <AccountValuationStatus line={line} pending={pending} failed={failed} />
                    {typeof row.version === 'string' && asOf !== todayKey() && row[config.amountField] != null && (
                      <Button size='sm' disabled={confirmValue.isPending} onClick={() => confirmValue.mutate(row)}>
                        잔고 그대로 맞음
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
      <RecordSheet
        resource={config.resource}
        record={creating ? null : editing}
        open={creating || editing !== null}
        onClose={() => {
          setCreating(false);
          onSelect(null);
        }}
      />
    </Section>
  );
}

/** "Nothing else to record" is a statement the user makes; without it, a category with no rows stays unknown, not zero. */
export function CoverageConfirm({ onlyDebt = false }: { onlyDebt?: boolean }) {
  const client = useQueryClient();
  const confirm = useConfirm();
  const portfolio = useQuery({ queryKey: ['finance', 'portfolio'], queryFn: financeApi.portfolio });
  const coverage = useMutation({
    mutationFn: () =>
      customInstance({
        url: '/api/finance/coverage',
        method: 'PUT',
        data: { kinds: onlyDebt ? [...new Set([...(portfolio.data?.coverage ?? []), 'liability'])] : ['cash', 'holding', 'liability', 'other'] },
      }),
    onSuccess: () => {
      notify.success('입력 완료로 확인했습니다');
      return Promise.all([client.invalidateQueries({ queryKey: ['finance'] }), client.invalidateQueries({ queryKey: getSummaryQueryKey() })]);
    },
    onError: notify.error,
  });
  const ask = async () => {
    const ok = await confirm({
      title: onlyDebt ? '부채가 없음을 확인하나요?' : '모든 자산과 부채를 기록했나요?',
      description: onlyDebt
        ? '기록할 부채가 없음을 확인합니다. 다른 자산의 입력 완료 여부는 유지됩니다.'
        : '현금·투자·부채·기타 자산을 빠짐없이 기록했고, 기록이 없는 분류는 실제로 없다는 뜻이라면 확인하세요. 그 뒤로는 빈 분류를 0으로 보고 합계를 확정합니다.',
      confirmLabel: '입력 완료',
    });
    if (ok) coverage.mutate();
  };
  return (
    <div className='flex flex-wrap items-center gap-3 rounded-lg border border-dashed p-4 text-ui'>
      <p className='flex-1 text-muted-foreground'>
        {onlyDebt
          ? portfolio.data?.coverage?.includes('liability')
            ? '부채 없음 확인 완료'
            : '부채가 없다면 확인하세요.'
          : '빠짐없이 기록했다면 입력 완료를 확인해야 합계가 확정됩니다.'}
      </p>
      <Button size='sm' disabled={coverage.isPending || portfolio.isPending || portfolio.isError} onClick={() => void ask()}>
        {onlyDebt ? '부채 없음 확인' : '입력 완료 확인'}
      </Button>
    </div>
  );
}

export function AccountsView({ recordId, showCoverage = true }: { recordId: number | null; showCoverage?: boolean }) {
  // Deep links (/finance/accounts?record=) point at accounts, the primary list here.
  const [accountId, setAccountId] = useRecordParam(recordId);
  const [liabilityId, setLiabilityId] = useState<number | null>(null);
  const [otherId, setOtherId] = useState<number | null>(null);
  const [checkingIn, setCheckingIn] = useState(false);
  const portfolio = useQuery({ queryKey: ['finance', 'portfolio'], queryFn: financeApi.portfolio });
  const lines = portfolio.data?.lines ?? [];
  const selection = [
    [accountId, setAccountId],
    [liabilityId, setLiabilityId],
    [otherId, setOtherId],
  ] as const;

  return (
    <>
      <div className='mb-3 flex justify-end'>
        <Button onClick={() => setCheckingIn(true)}>
          <RefreshCw /> 잔고 한 번에 업데이트
        </Button>
      </div>
      <BalanceCheckInSheet open={checkingIn} onOpenChange={setCheckingIn} />
      <QueryStatus pending={portfolio.isPending} error={portfolio.error} retry={portfolio.refetch} label='자산 검증' rows={1} />
      {LISTS.map((config, i) => (
        <RecordList
          key={config.resource}
          config={config}
          lines={lines}
          pending={portfolio.isFetching}
          failed={portfolio.isError}
          selected={selection[i][0]}
          onSelect={selection[i][1]}
        />
      ))}
      {showCoverage && <CoverageConfirm />}
    </>
  );
}
