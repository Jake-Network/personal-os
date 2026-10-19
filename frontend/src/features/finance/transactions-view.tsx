'use client';

import { useMemo, useState } from 'react';

import { useMutation, useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronLeft, ChevronRight, Plus, Undo2 } from 'lucide-react';

import { customInstance } from '@/api-client/custom-client';
import { TabToolbar } from '@/components/area-layout';
import { EmptyState } from '@/components/empty-state';
import { InfoPopover } from '@/components/info-popover';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QualityBadge } from '@/components/quality-badge';
import { QueryStatus } from '@/components/query-status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { dateOnly, timestamp } from '@/lib/utils/format';
import { cn } from '@/lib/utils';
import { compareKeys, todayKey, zonedDayKey } from '@/lib/utils/zoned';

import type { Row } from '@/features/personal-data/api/resource-api';
import { RecordSheet } from '@/features/personal-data/components/record-sheet';
import { useResourceRows } from '@/features/personal-data/hooks/use-resource';
import { useRecordParam } from '@/features/personal-data/hooks/use-record-param';
import { SourceCalendar } from '@/features/plan/source-calendar';
import { useStoredView, ViewToggle } from '@/features/plan/view-toggle';

import { CSV_FORMAT_HELP, FinanceImport } from './import-view';
import { type LedgerDraft, type LedgerEntry, LedgerEntrySheet } from './ledger-view';
import { issueFlags, money } from './presentation';
import { TRANSACTION_KIND_LABEL } from './transaction-kinds';

type Trend = { cashflow_by_currency: Record<string, { income: string; expense: string; net_cashflow: string }>; data_quality_flags: string[] };

type Filter = 'all' | 'income' | 'expense' | 'move';
const FILTERS: [Filter, string][] = [
  ['all', '전체'],
  ['income', '수입'],
  ['expense', '지출'],
  ['move', '이체·투자'],
];
const GROUP: Record<string, Filter> = {
  income: 'income',
  dividend: 'income',
  interest: 'income',
  expense: 'expense',
  fee: 'expense',
  tax: 'expense',
  transfer: 'move',
  buy: 'move',
  sell: 'move',
  repayment: 'move',
  split: 'move',
};

interface ListRow {
  key: string;
  /** Sort key: local day, then instant. */
  sort: string;
  day: string;
  time?: string;
  kind: string;
  title: string;
  detail?: string;
  amount: string | null;
  currency: string;
  ledger?: LedgerEntry;
  cashflow?: Row;
  reversed: boolean;
}

function toRows(ledger: LedgerEntry[], cashflow: Row[], year: number): ListRow[] {
  const reversed = new Set(ledger.filter(e => e.kind === 'reversal' && e.reverses_id).map(e => e.reverses_id));
  const fromLedger = ledger.map<ListRow>(e => {
    const day = zonedDayKey(e.occurred_at);
    return {
      key: `ledger:${e.id}`,
      sort: `${day}T${e.occurred_at}`,
      day,
      time: e.occurred_at,
      kind: e.kind,
      title: e.note || e.source,
      detail: e.note ? e.source : undefined,
      amount: e.amount,
      currency: e.currency,
      ledger: e,
      reversed: reversed.has(e.id),
    };
  });
  const fromCashflow = cashflow
    .filter(r => String(r.occurred_on).startsWith(String(year)))
    .map<ListRow>(r => ({
      key: `cashflow:${r.id}`,
      sort: `${r.occurred_on}T`,
      day: String(r.occurred_on),
      kind: String(r.kind),
      title: String(r.description || r.category || TRANSACTION_KIND_LABEL[String(r.kind)]),
      detail: r.description && r.category ? String(r.category) : undefined,
      amount: r.amount as string,
      currency: (r.currency as string) ?? 'KRW',
      cashflow: r,
      reversed: false,
    }));
  return [...fromLedger, ...fromCashflow].sort((a, b) => b.sort.localeCompare(a.sort));
}

function YearSummary({ year }: { year: number }) {
  const trend = useQuery({ queryKey: ['finance', 'trends', year], queryFn: () => customInstance<Trend>({ url: `/api/finance/trends/${year}` }) });
  const entries = Object.entries(trend.data?.cashflow_by_currency ?? {});
  if (trend.error) return <QueryStatus pending={false} error={trend.error} retry={trend.refetch} label='연간 합계' />;
  if (!trend.data) return null;
  return (
    <div className='mb-5 rounded-lg border bg-card p-4'>
      <div className='mb-2 flex flex-wrap items-center gap-2'>
        <h3 className='text-ui font-semibold'>{year}년 수입·지출 합계 (거래 기록 기준)</h3>
        <QualityBadge flags={issueFlags(trend.data.data_quality_flags)} label='기록 범위 확인' />
        <InfoPopover>
          <p>거래 기록에 남긴 수입·지출만 통화별로 합산합니다. 다른 통화는 환율로 합치지 않습니다.</p>
          <p>이체·매매·상환은 수입이나 지출에 넣지 않습니다. 직접 입력한 수입·지출 목록은 이 합계에 들어가지 않습니다.</p>
        </InfoPopover>
      </div>
      {entries.length === 0 ? (
        <p className='text-ui text-muted-foreground'>이 해에 거래 기록으로 남긴 수입·지출이 없습니다. 직접 입력한 수입·지출은 이 합계에 넣지 않습니다.</p>
      ) : (
        <dl className='grid gap-2 sm:grid-cols-3'>
          {entries.map(([currency, amount]) => (
            <div key={currency} className='contents'>
              <div>
                <dt className='text-xs text-muted-foreground'>수입 {currency !== 'KRW' && currency}</dt>
                <dd className='tabular-nums'>{money(amount.income, currency)}</dd>
              </div>
              <div>
                <dt className='text-xs text-muted-foreground'>지출 {currency !== 'KRW' && currency}</dt>
                <dd className='tabular-nums'>{money(amount.expense, currency)}</dd>
              </div>
              <div>
                <dt className='text-xs text-muted-foreground'>차이 {currency !== 'KRW' && currency}</dt>
                <dd className='tabular-nums'>{money(amount.net_cashflow, currency)}</dd>
              </div>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function PlannedExpenses() {
  const [view, setView] = useStoredView('finance-planned');
  const rows = useResourceRows('planned-expenses');
  const [selected, setSelected] = useState<Row | 'new' | null>(null);
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
          <Button size='sm' onClick={() => setSelected('new')}>
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
                    <button type='button' onClick={() => setSelected(r)} className='flex w-full items-center gap-3 px-1 py-2.5 text-left hover:bg-muted/50'>
                      <span className={cn('w-28 shrink-0 text-ui tabular-nums', past ? 'text-faint' : 'text-muted-foreground')}>{dateOnly(String(r.due_on))}</span>
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
      {selected && <RecordSheet resource='planned-expenses' record={selected === 'new' ? null : selected} open onClose={() => setSelected(null)} />}
    </Section>
  );
}

export function TransactionsView({ recordId }: { recordId: number | null }) {
  const [year, setYear] = useState(() => Number(todayKey().slice(0, 4)));
  const [filter, setFilter] = useState<Filter>('all');
  const [ledgerDraft, setLedgerDraft] = useState<{ draft: LedgerDraft; title: string } | null>(null);
  const [creatingCashflow, setCreatingCashflow] = useState(false);
  const [plannedNew, setPlannedNew] = useState(false);
  // Deep links point at directly entered income/expense rows, the editable records on this screen.
  const [cashflowId, setCashflowId] = useRecordParam(recordId);

  const ledger = useQuery({
    queryKey: ['finance', 'transactions', year],
    queryFn: () => customInstance<LedgerEntry[]>({ url: '/api/finance/transactions', params: { year } }),
  });
  const cashflow = useResourceRows('cashflow-entries');
  const observe = useMutation({
    mutationFn: () => customInstance({ url: '/api/finance/observed-valuations', method: 'POST' }),
    onSuccess: () => notify.success('오늘 평가액을 기록했습니다'),
    onError: notify.error,
  });

  const rows = useMemo(() => toRows(ledger.data ?? [], cashflow.data ?? [], year), [ledger.data, cashflow.data, year]);
  const shown = filter === 'all' ? rows : rows.filter(r => GROUP[r.kind] === filter);
  const editingCashflow = cashflowId === null ? null : (cashflow.data?.find(r => r.id === cashflowId) ?? null);
  const startLedger = (title: string, extra: Partial<LedgerDraft> = {}) => setLedgerDraft({ title, draft: { request_id: crypto.randomUUID(), ...extra } });

  return (
    <>
      <TabToolbar>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant='primary'>
              <Plus /> 거래 추가 <ChevronDown />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='start'>
            <DropdownMenuItem onSelect={() => setCreatingCashflow(true)}>수입·지출</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => startLedger('거래 기록')}>이체·매매·상환 등 거래</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setPlannedNew(true)}>예정 지출</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button disabled={observe.isPending} onClick={() => observe.mutate()}>
          오늘 평가액 기록
        </Button>
        <InfoPopover label='오늘 평가액 기록 안내'>
          <p>지금 기록된 잔액·수량·시세로 오늘의 평가액을 남깁니다. 확정된 월말 기록과는 따로 보관합니다.</p>
          <p>거래를 기록해도 잔액과 수량은 자동으로 바뀌지 않으니, 실제 값은 계좌·투자에서 갱신하세요.</p>
        </InfoPopover>
        <div className='ml-auto flex items-center gap-1' role='group' aria-label='조회 연도'>
          <Button size='icon-sm' variant='ghost' aria-label='이전 해' onClick={() => setYear(y => y - 1)}>
            <ChevronLeft />
          </Button>
          <span className='min-w-14 text-center text-ui font-medium tabular-nums'>{year}년</span>
          <Button size='icon-sm' variant='ghost' aria-label='다음 해' onClick={() => setYear(y => y + 1)}>
            <ChevronRight />
          </Button>
        </div>
      </TabToolbar>

      <YearSummary year={year} />

      <Section
        title='거래'
        count={shown.length}
        actions={
          <div className='flex gap-1' role='group' aria-label='거래 종류'>
            {FILTERS.map(([value, label]) => (
              <button
                key={value}
                type='button'
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
                className={cn('h-7 rounded-full px-2.5 text-xs text-muted-foreground hover:bg-muted', filter === value && 'bg-accent font-medium text-accent-foreground')}>
                {label}
              </button>
            ))}
          </div>
        }>
        <QueryStatus pending={ledger.isPending || cashflow.isPending} error={ledger.error ?? cashflow.error} retry={() => Promise.all([ledger.refetch(), cashflow.refetch()])} label='거래' />
        {!ledger.isPending && !cashflow.isPending && shown.length === 0 && <EmptyState className='py-6'>{year}년에 기록된 거래가 없습니다.</EmptyState>}
        {shown.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className='w-28'>날짜</TableHead>
                <TableHead>내용</TableHead>
                <TableHead className='text-right'>금액</TableHead>
                <TableHead className='w-10'>
                  <span className='sr-only'>동작</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map(r => (
                <TableRow
                  key={r.key}
                  className={cn(r.cashflow && 'cursor-pointer', r.reversed && 'text-faint')}
                  onClick={() => r.cashflow && setCashflowId(r.cashflow.id)}>
                  <TableCell className='tabular-nums'>
                    {dateOnly(r.day)}
                    {r.ledger && <span className='block text-xs text-faint' title={`입력 ${timestamp(r.ledger.recorded_at)}`}>거래 기록</span>}
                  </TableCell>
                  <TableCell>
                    <span className='flex flex-wrap items-center gap-1.5'>
                      <Badge variant={GROUP[r.kind] === 'income' ? 'success' : GROUP[r.kind] === 'expense' ? 'default' : 'accent'}>{TRANSACTION_KIND_LABEL[r.kind] ?? r.kind}</Badge>
                      {r.cashflow ? (
                        <button type='button' className={cn('text-left hover:underline', r.reversed && 'line-through')} onClick={() => setCashflowId(r.cashflow!.id)}>
                          {r.title}
                        </button>
                      ) : (
                        <span className={cn(r.reversed && 'line-through')}>{r.title}</span>
                      )}
                      {r.reversed && <Badge>취소됨</Badge>}
                    </span>
                    {r.detail && <span className='block text-xs text-faint'>{r.detail}</span>}
                  </TableCell>
                  <TableCell className={cn('text-right tabular-nums', r.reversed && 'line-through')}>{r.amount ? money(r.amount, r.currency) : '—'}</TableCell>
                  <TableCell onClick={e => e.stopPropagation()}>
                    {r.ledger && r.ledger.kind !== 'reversal' && !r.reversed && (
                      <Button
                        size='icon-sm'
                        variant='ghost'
                        aria-label='이 거래 취소 기록'
                        title='이 거래 취소 기록'
                        onClick={() => startLedger('거래 취소 기록', { kind: 'reversal', reverses_id: r.ledger!.id, currency: r.ledger!.currency })}>
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

      {ledgerDraft && <LedgerEntrySheet draft={ledgerDraft.draft} title={ledgerDraft.title} onClose={() => setLedgerDraft(null)} />}
      <RecordSheet
        resource='cashflow-entries'
        record={creatingCashflow ? null : editingCashflow}
        open={creatingCashflow || editingCashflow !== null}
        onClose={() => {
          setCreatingCashflow(false);
          setCashflowId(null);
        }}
      />
      {plannedNew && <RecordSheet resource='planned-expenses' record={null} open onClose={() => setPlannedNew(false)} />}
    </>
  );
}
