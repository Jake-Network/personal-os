'use client';

import { useState } from 'react';

import { useMutation, useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Plus, Undo2 } from 'lucide-react';

import { customInstance } from '@/api-client/custom-client';
import { notify } from '@/components/notify';
import { CSV_FORMAT_HELP, FinanceImport } from './import-view';
import { PlannedExpenses } from './transactions-view';
import type { TransactionInputKind } from '@/api-client/model';

import { getCashflowEntries } from '@/api-client/generated/personal-data/personal-data';
import { householdCashflow } from '@/api-client/generated/portfolio/portfolio';
import { TabToolbar } from '@/components/area-layout';
import { EmptyState } from '@/components/empty-state';
import { InfoPopover } from '@/components/info-popover';
import { Section } from '@/components/page-container';
import { QualityBadge } from '@/components/quality-badge';
import { QueryStatus } from '@/components/query-status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { RecordSheet } from '@/features/personal-data/components/record-sheet';
import { useRecordParam } from '@/features/personal-data/hooks/use-record-param';
import { dateOnly } from '@/lib/utils/format';
import { todayKey } from '@/lib/utils/zoned';

import { CASHFLOW_CATEGORIES, cashflowCategories } from './cashflow-categories';
import { type LedgerDraft, type LedgerEntry, LedgerEntrySheet } from './ledger-view';
import { money } from './presentation';
import { TRANSACTION_KIND_LABEL } from './transaction-kinds';

const recordedMoney = (value: string | null, currency: string) => (value === null ? '미기록' : money(value, currency));
function moveMonth(month: string, delta: number) {
  const [year, index] = month.split('-').map(Number);
  const date = new Date(Date.UTC(year, index - 1 + delta, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`;
}

export function CashflowView({ recordId, source = 'cashflow_entries' }: { recordId: number | null; source?: string }) {
  const [tab, setTab] = useState(source === 'planned_expenses' ? 'planned' : 'ledger');
  const observe = useMutation({
    mutationFn: () => customInstance({ url: '/api/finance/observed-valuations', method: 'POST' }),
    onSuccess: () => notify.success('오늘 평가액을 기록했습니다'),
    onError: notify.error,
  });
  const [month, setMonth] = useState(() => todayKey().substring(0, 7));
  const [kind, setKind] = useState('');
  const [category, setCategory] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useRecordParam(source === 'cashflow_entries' ? recordId : null);
  const [draft, setDraft] = useState<LedgerDraft | null>(null);
  const query = useQuery({
    queryKey: ['finance', 'cashflow', month, kind, category, search, page],
    queryFn: ({ signal }) =>
      householdCashflow(
        {
          month,
          scope: 'all',
          kind: kind === 'income' || kind === 'expense' ? kind : undefined,
          transaction_kind: kind && kind !== 'income' && kind !== 'expense' ? (kind as TransactionInputKind) : undefined,
          category: category || undefined,
          search: search || undefined,
          page,
          page_size: 50,
        },
        undefined,
        signal,
      ),
  });
  const detail = useQuery({
    queryKey: ['finance', 'cashflow-entry', selected],
    queryFn: async ({ signal }) => ({ ...(await getCashflowEntries(selected!, undefined, signal)) }),
    enabled: selected !== null,
  });
  const [linkedDismissed, setLinkedDismissed] = useState(false);
  const linkedTransaction = useQuery({
    queryKey: ['finance', 'transaction', recordId],
    queryFn: () => customInstance<LedgerEntry>({ url: `/api/finance/transactions/${recordId}` }),
    enabled: source === 'financial_transactions' && recordId !== null && !linkedDismissed,
  });
  const data = query.data;
  const changeMonth = (value: string) => {
    if (value) {
      setMonth(value);
      setPage(1);
    }
  };
  const close = () => {
    setCreating(false);
    setSelected(null);
  };

  return (
    <>
      {source === 'financial_transactions' && recordId !== null && !linkedDismissed && (
        <Section title='선택한 거래'>
          <QueryStatus pending={linkedTransaction.isPending} error={linkedTransaction.error} retry={linkedTransaction.refetch} label='거래' />
          {linkedTransaction.data && (
            <div className='flex flex-wrap items-center gap-3'>
              <span>
                {TRANSACTION_KIND_LABEL[linkedTransaction.data.kind]} · {linkedTransaction.data.note || linkedTransaction.data.source}
              </span>
              <span>{money(linkedTransaction.data.amount, linkedTransaction.data.currency)}</span>
              {linkedTransaction.data.is_reversed ? (
                <Badge>취소됨</Badge>
              ) : (
                linkedTransaction.data.kind !== 'reversal' && (
                  <Button
                    onClick={() =>
                      setDraft({
                        request_id: crypto.randomUUID(),
                        kind: 'reversal',
                        reverses_id: linkedTransaction.data!.id,
                        currency: linkedTransaction.data!.currency,
                      })
                    }>
                    거래 취소
                  </Button>
                )
              )}
            </div>
          )}
          <Button onClick={() => setLinkedDismissed(true)}>선택 닫기</Button>
        </Section>
      )}
      <div className='mb-4 flex gap-2' role='group' aria-label='장부 보기'>
        <Button aria-pressed={tab === 'ledger'} onClick={() => setTab('ledger')}>
          전체 기록
        </Button>
        <Button aria-pressed={tab === 'planned'} onClick={() => setTab('planned')}>
          예정 지출
        </Button>
      </div>
      {tab === 'planned' ? (
        <PlannedExpenses recordId={source === 'planned_expenses' ? recordId : null} />
      ) : (
        <>
          <TabToolbar>
            <Button variant='primary' onClick={() => setCreating(true)}>
              <Plus /> 기록 추가
            </Button>
            <Button onClick={() => setDraft({ request_id: crypto.randomUUID() })}>거래 추가</Button>
            <Button disabled={observe.isPending} onClick={() => observe.mutate()}>
              오늘 평가액 기록
            </Button>
            <InfoPopover label='장부 안내'>
              <p>기록한 수입·지출만 합산합니다. 수지는 기록된 차액이며 저축액을 뜻하지 않습니다. 계좌 잔액은 따로 관리합니다.</p>
              <p>기존 거래의 수입·배당·이자·지출·수수료·세금도 포함합니다. 취소된 거래와 이체·매매·상환은 합계에서 제외합니다.</p>
              <p>필터는 목록·월 합계·분류·최근 6개월에 함께 적용됩니다. 합계는 현재 페이지에 제한되지 않습니다.</p>
            </InfoPopover>
            <div className='ml-auto flex items-center gap-1'>
              <Button variant='ghost' size='icon-sm' aria-label='이전 달' onClick={() => changeMonth(moveMonth(month, -1))}>
                <ChevronLeft />
              </Button>
              <Input aria-label='조회 월' type='month' value={month} onChange={event => changeMonth(event.target.value)} className='w-40' />
              <Button variant='ghost' size='icon-sm' aria-label='다음 달' onClick={() => changeMonth(moveMonth(month, 1))}>
                <ChevronRight />
              </Button>
            </div>
          </TabToolbar>
          <div className='mb-5 grid gap-3 sm:grid-cols-3'>
            <div>
              <Label htmlFor='cashflow-kind'>수입·지출</Label>
              <NativeSelect
                id='cashflow-kind'
                value={kind}
                onChange={event => {
                  setKind(event.target.value);
                  setCategory('');
                  setPage(1);
                }}>
                <option value=''>전체</option>
                <option value='income'>수입</option>
                <option value='expense'>지출</option>
                {['transfer', 'buy', 'sell', 'repayment', 'split', 'reversal', 'dividend', 'interest', 'fee', 'tax'].map(value => (
                  <option key={value} value={value}>
                    {TRANSACTION_KIND_LABEL[value]}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor='cashflow-category'>분류</Label>
              <Input
                id='cashflow-category'
                list='cashflow-categories'
                value={category}
                placeholder='전체 분류'
                onChange={event => {
                  setCategory(event.target.value);
                  setPage(1);
                }}
              />
              <datalist id='cashflow-categories'>
                {[...cashflowCategories(kind), '미분류'].map(value => (
                  <option key={value} value={value} />
                ))}
              </datalist>
            </div>
            <div>
              <Label htmlFor='cashflow-search'>메모 검색</Label>
              <Input
                id='cashflow-search'
                type='search'
                value={search}
                placeholder='기록한 메모'
                onChange={event => {
                  setSearch(event.target.value);
                  setPage(1);
                }}
              />
            </div>
          </div>
          <QueryStatus pending={query.isPending} error={query.error} retry={query.refetch} label='가계부' />
          {selected !== null && <QueryStatus pending={detail.isPending} error={detail.error} retry={detail.refetch} label='선택한 기록' />}
          {data && (
            <>
              <Section
                title='기록된 월별 수입·지출'
                actions={<QualityBadge flags={data.data_quality_flags.map(code => ({ code }))} label='기록 범위 확인' />}>
                <dl className='grid grid-cols-1 gap-3 sm:grid-cols-3'>
                  {[
                    ['수입', data.summary.income],
                    ['지출', data.summary.expense],
                    ['수지', data.summary.net],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt className='text-ui text-muted-foreground'>{label}</dt>
                      <dd className='text-title font-semibold tabular-nums'>{recordedMoney(value, data.currency)}</dd>
                    </div>
                  ))}
                </dl>
                {data.data_quality_flags.includes('cashflow_mixed_sources') && (
                  <p className='mt-3 text-ui text-warning'>가계부와 거래 기록을 함께 합산했습니다. 같은 수입·지출을 중복 입력했는지 확인하세요.</p>
                )}
                {data.summary.foreign_count > 0 && (
                  <p className='mt-3 text-ui text-warning'>
                    {data.currency === 'KRW'
                      ? `외화 기록 ${data.summary.foreign_count}건은 원화 합계에서 제외했습니다.`
                      : `다른 통화 기록 ${data.summary.foreign_count}건은 ${data.currency} 합계에서 제외했습니다.`}
                  </p>
                )}
              </Section>
              <Section title='분류별 지출'>
                {data.categories.length === 0 ? (
                  <EmptyState className='py-5'>집계할 {data.currency === 'KRW' ? '원화' : data.currency} 지출이 미기록 상태입니다.</EmptyState>
                ) : (
                  <ul className='divide-y'>
                    {data.categories.map(item => (
                      <li key={item.category} className='flex items-center justify-between gap-3 py-2'>
                        <span>{item.category}</span>
                        <span className='text-right tabular-nums'>
                          {money(item.amount, data.currency)} <span className='ml-2 text-xs text-muted-foreground'>{item.share}%</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
              <Section title='내역' count={data.total}>
                {data.total === 0 && (
                  <EmptyState
                    action={
                      <Button onClick={() => setCreating(true)}>
                        <Plus /> 기록 추가
                      </Button>
                    }>
                    조건에 맞는 기록이 없습니다.
                  </EmptyState>
                )}
                {data.items.length > 0 && (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>날짜·내용</TableHead>
                        <TableHead className='text-right'>금액</TableHead>
                        <TableHead>
                          <span className='sr-only'>기록 관리</span>
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.items.map(item => (
                        <TableRow key={`${item.source}:${item.id}`}>
                          <TableCell>
                            <span className='block text-xs text-muted-foreground'>
                              {dateOnly(item.occurred_on)} · {item.category}
                            </span>
                            <span className={item.is_reversed ? 'line-through' : ''}>
                              {item.description || TRANSACTION_KIND_LABEL[item.original_kind]}
                            </span>
                            <span className='mt-1 flex flex-wrap gap-1'>
                              <Badge variant={item.kind === 'income' ? 'success' : 'default'}>{TRANSACTION_KIND_LABEL[item.original_kind]}</Badge>
                              {item.source === 'financial_transactions' && <Badge>거래 기록</Badge>}
                              {item.is_reversed && <Badge>취소됨</Badge>}
                            </span>
                          </TableCell>
                          <TableCell className={`text-right tabular-nums ${item.is_reversed ? 'line-through text-muted-foreground' : ''}`}>
                            {item.amount === null
                              ? item.quantity
                                ? `수량 ${item.quantity}`
                                : '금액 없음'
                              : money(item.amount, item.currency ?? undefined)}
                          </TableCell>
                          <TableCell>
                            {item.source === 'cashflow_entries' ? (
                              <Button size='sm' onClick={() => setSelected(item.id)} aria-label={`${item.description || item.category} 수정`}>
                                수정
                              </Button>
                            ) : (
                              !item.is_reversed &&
                              item.original_kind !== 'reversal' && (
                                <Button
                                  size='icon-sm'
                                  variant='ghost'
                                  aria-label={`${item.description || item.category} 거래 취소`}
                                  onClick={() =>
                                    setDraft({
                                      request_id: crypto.randomUUID(),
                                      kind: 'reversal',
                                      reverses_id: item.id,
                                      currency: item.currency ?? undefined,
                                    })
                                  }>
                                  <Undo2 />
                                </Button>
                              )
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
                {data.total > data.page_size && (
                  <div className='mt-3 flex items-center justify-center gap-3'>
                    <Button aria-label='이전 페이지' disabled={page <= 1} onClick={() => setPage(value => value - 1)}>
                      <ChevronLeft />
                    </Button>
                    <span className='text-ui tabular-nums'>
                      {data.page} / {Math.ceil(data.total / data.page_size)}
                    </span>
                    <Button aria-label='다음 페이지' disabled={page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}>
                      <ChevronRight />
                    </Button>
                  </div>
                )}
              </Section>
              <Section
                title='최근 6개월 소비 추이'
                info={`선택한 조건의 기록된 ${data.currency === 'KRW' ? '원화' : data.currency} 수입·지출입니다. 미기록 월은 0과 구분합니다.`}>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>월</TableHead>
                      <TableHead className='text-right'>수입</TableHead>
                      <TableHead className='text-right'>지출</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.trend.map(item => (
                      <TableRow key={item.month}>
                        <TableCell>
                          {item.month.replace('-', '년 ')}월
                          {item.foreign_count > 0 && <span className='block text-xs text-warning'>다른 통화 제외</span>}
                        </TableCell>
                        <TableCell className='text-right tabular-nums'>{recordedMoney(item.income, data.currency)}</TableCell>
                        <TableCell className='text-right tabular-nums'>{recordedMoney(item.expense, data.currency)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Section>
            </>
          )}
          <Section title='CSV로 잔액·보유 종목 가져오기' info={CSV_FORMAT_HELP}>
            <details className='rounded-lg border p-4'>
              <summary className='cursor-pointer'>CSV 붙여넣기</summary>
              <FinanceImport />
            </details>
          </Section>
        </>
      )}
      {(creating || (selected !== null && detail.data)) && (
        <RecordSheet
          resource='cashflow-entries'
          record={creating ? null : (detail.data ?? null)}
          open
          onClose={close}
          title={creating ? '가계부 기록 추가' : '가계부 기록 수정'}
          defaults={{ occurred_on: todayKey(), kind: 'expense', currency: 'KRW' }}
          hidden={['currency']}
          labels={{ description: '메모' }}
          suggestions={{ category: { dependsOn: 'kind', options: CASHFLOW_CATEGORIES } }}
          note={
            creating
              ? '원화로 기록합니다. 계좌 잔액은 바뀌지 않습니다.'
              : `통화: ${String(detail.data?.currency ?? 'KRW')}. 계좌 잔액은 바뀌지 않습니다.`
          }
        />
      )}
      {draft && <LedgerEntrySheet draft={draft} title={draft.kind === 'reversal' ? '거래 취소 기록' : '거래 기록'} onClose={() => setDraft(null)} />}
    </>
  );
}
