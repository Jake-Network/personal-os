'use client';

import { useState } from 'react';

import { useMutation, useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Plus, Undo2 } from 'lucide-react';

import { customInstance } from '@/api-client/custom-client';
import { TabToolbar } from '@/components/area-layout';
import { EmptyState } from '@/components/empty-state';
import { InfoPopover } from '@/components/info-popover';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { dateOnly, timestamp } from '@/lib/utils/format';
import { cn } from '@/lib/utils';
import { compareKeys, todayKey, zonedDayKey } from '@/lib/utils/zoned';

import type { Row } from '@/features/personal-data/api/resource-api';
import { RecordSheet } from '@/features/personal-data/components/record-sheet';
import { useResourceRows } from '@/features/personal-data/hooks/use-resource';
import { SourceCalendar } from '@/features/plan/source-calendar';
import { useStoredView, ViewToggle } from '@/features/plan/view-toggle';

import { CSV_FORMAT_HELP, FinanceImport } from './import-view';
import { type LedgerDraft, type LedgerEntry, LedgerEntrySheet } from './ledger-view';
import { money } from './presentation';
import { TRANSACTION_KIND_LABEL } from './transaction-kinds';

export function PlannedExpenses({ recordId = null }: { recordId?: number | null }) {
  const [view, setView] = useStoredView('finance-planned');
  const rows = useResourceRows('planned-expenses');
  const [selected, setSelected] = useState<Row | 'new' | null>(null);
  const linked = selected ?? rows.data?.find(row => row.id === recordId) ?? null;
  const [dismissed, setDismissed] = useState(false);
  const today = todayKey();
  const sorted = [...(rows.data ?? [])].sort((a, b) => String(a.due_on).localeCompare(String(b.due_on)));
  return (
    <Section
      title='예정 지출'
      count={rows.data?.length}
      info='앞으로 나갈 돈을 기록해 두면 상담에서 생활비 계획에 함께 고려합니다. 실제로 지출하면 수입·지출이나 거래로 따로 기록하세요.'
      actions={
        <>
          <ViewToggle value={view} onChange={setView} />
          <Button size='sm' onClick={() => (setDismissed(false), setSelected('new'))}>
            <Plus /> 추가
          </Button>
        </>
      }>
      {view === 'calendar' ? (
        <SourceCalendar sources={['planned-expenses']} />
      ) : (
        <>
          <QueryStatus pending={rows.isPending} error={rows.error} retry={rows.refetch} label='예정 지출' rows={2} />
          {rows.data?.length === 0 && <EmptyState className='py-5'>예정된 큰 지출이 있다면 기록하세요.</EmptyState>}
          {sorted.length > 0 && (
            <ul className='divide-y'>
              {sorted.map(r => {
                const past = compareKeys(String(r.due_on), today) < 0;
                return (
                  <li key={r.id}>
                    <button
                      type='button'
                      onClick={() => (setDismissed(false), setSelected(r))}
                      className='flex w-full items-center gap-3 px-1 py-2.5 text-left hover:bg-muted/50'>
                      <span className={cn('w-28 shrink-0 text-ui tabular-nums', past ? 'text-faint' : 'text-muted-foreground')}>
                        {dateOnly(String(r.due_on))}
                      </span>
                      <span className='flex-1 font-medium'>{String(r.name)}</span>
                      {past && <Badge>지난 날짜</Badge>}
                      <span className='tabular-nums'>{money(r.amount as string, (r.currency as string) ?? 'KRW')}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
      {linked && !dismissed && (
        <RecordSheet
          resource='planned-expenses'
          record={linked === 'new' ? null : linked}
          open
          onClose={() => {
            setSelected(null);
            setDismissed(true);
          }}
        />
      )}
    </Section>
  );
}

export function TransactionsView() {
  const [year, setYear] = useState(() => Number(todayKey().slice(0, 4)));
  const [ledgerDraft, setLedgerDraft] = useState<{ draft: LedgerDraft; title: string } | null>(null);
  const [plannedNew, setPlannedNew] = useState(false);
  const ledger = useQuery({
    queryKey: ['finance', 'transactions', year],
    queryFn: () => customInstance<LedgerEntry[]>({ url: '/api/finance/transactions', params: { year } }),
  });
  const observe = useMutation({
    mutationFn: () => customInstance({ url: '/api/finance/observed-valuations', method: 'POST' }),
    onSuccess: () => notify.success('오늘 평가액을 기록했습니다'),
    onError: notify.error,
  });
  const rows = (ledger.data ?? []).filter(row => ['transfer', 'buy', 'sell', 'repayment', 'split', 'reversal'].includes(row.kind));
  const startLedger = (title: string, extra: Partial<LedgerDraft> = {}) =>
    setLedgerDraft({ title, draft: { request_id: crypto.randomUUID(), ...extra } });
  return (
    <>
      <TabToolbar>
        <Button variant='primary' onClick={() => startLedger('거래 기록')}>
          <Plus /> 거래 추가
        </Button>
        <Button onClick={() => setPlannedNew(true)}>예정 지출 추가</Button>
        <Button disabled={observe.isPending} onClick={() => observe.mutate()}>
          오늘 평가액 기록
        </Button>
        <InfoPopover label='거래 기록 안내'>
          <p>거래 기록은 계좌 잔액과 보유 수량을 바꾸지 않습니다. 실제 값은 계좌·투자에서 갱신하세요.</p>
          <p>생활 수입·지출과 소비 요약은 가계부에서 관리합니다.</p>
        </InfoPopover>
        <div className='ml-auto flex items-center gap-1' role='group' aria-label='조회 연도'>
          <Button size='icon-sm' variant='ghost' aria-label='이전 해' onClick={() => setYear(value => value - 1)}>
            <ChevronLeft />
          </Button>
          <span className='text-ui tabular-nums'>{year}년</span>
          <Button size='icon-sm' variant='ghost' aria-label='다음 해' onClick={() => setYear(value => value + 1)}>
            <ChevronRight />
          </Button>
        </div>
      </TabToolbar>
      <Section title='이체·투자·상환' count={rows.length}>
        <QueryStatus pending={ledger.isPending} error={ledger.error} retry={ledger.refetch} label='거래' />
        {!ledger.isPending && !ledger.error && rows.length === 0 && <EmptyState>이 해에 기록된 이체·투자·상환이 없습니다.</EmptyState>}
        {rows.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>날짜</TableHead>
                <TableHead>내용</TableHead>
                <TableHead className='text-right'>금액</TableHead>
                <TableHead>
                  <span className='sr-only'>거래 관리</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(row => (
                <TableRow key={row.id} className={cn(row.is_reversed && 'text-faint')}>
                  <TableCell>
                    {dateOnly(zonedDayKey(row.occurred_at))}
                    <span className='block text-xs text-faint' title={`입력 ${timestamp(row.recorded_at)}`}>
                      거래 기록
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge>{TRANSACTION_KIND_LABEL[row.kind]}</Badge>{' '}
                    <span className={row.is_reversed ? 'line-through' : ''}>{row.note || row.source}</span>
                    {row.is_reversed && <Badge>취소됨</Badge>}
                  </TableCell>
                  <TableCell className='text-right tabular-nums'>{row.amount === null ? '—' : money(row.amount, row.currency)}</TableCell>
                  <TableCell>
                    {row.kind !== 'reversal' && !row.is_reversed && (
                      <Button
                        size='icon-sm'
                        variant='ghost'
                        aria-label='이 거래 취소 기록'
                        onClick={() => startLedger('거래 취소 기록', { kind: 'reversal', reverses_id: row.id, currency: row.currency })}>
                        <Undo2 />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
      <PlannedExpenses />
      <Section title='CSV로 잔액·보유 종목 가져오기' info={CSV_FORMAT_HELP}>
        <details className='rounded-lg border p-4'>
          <summary className='cursor-pointer text-ui font-medium'>CSV 붙여넣기</summary>
          <div className='mt-3'>
            <FinanceImport />
          </div>
        </details>
      </Section>
      {ledgerDraft && (
        <LedgerEntrySheet
          draft={ledgerDraft.draft}
          title={ledgerDraft.title}
          allowedKinds={['transfer', 'buy', 'sell', 'dividend', 'interest', 'fee', 'tax', 'repayment', 'split', 'reversal']}
          onClose={() => setLedgerDraft(null)}
        />
      )}
      {plannedNew && <RecordSheet resource='planned-expenses' record={null} open onClose={() => setPlannedNew(false)} />}
    </>
  );
}
