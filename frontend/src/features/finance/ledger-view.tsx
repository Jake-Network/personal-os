'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import { PageContainer, PageHeader } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { DataForm } from '@/features/personal-data/components/data-form';
import { useSchemaFields } from '@/features/personal-data/hooks/use-schema-fields';
import { money, timestamp } from './presentation';
import { FinanceImport } from './import-view';
import { TRANSACTION_KIND_LABEL as kinds } from './transaction-kinds';

const labels = {
  request_id: '요청 ID',
  kind: '거래 종류',
  occurred_at: '실제 거래 시각',
  account_id: '출금·기록 계좌',
  counterparty_account_id: '도착 계좌',
  holding_id: '보유자산',
  amount: '금액',
  currency: '통화',
  quantity: '변경 수량',
  source: '근거·출처',
  note: '메모',
  reverses_id: '취소할 원본 거래',
};
type Entry = {
  id: number;
  kind: string;
  occurred_at: string;
  recorded_at: string;
  amount: string | null;
  currency: string;
  source: string;
  note: string | null;
};
type Trend = { cashflow_by_currency: Record<string, { income: string; expense: string; net_cashflow: string }>; data_quality_flags: string[] };
export function FinanceLedger() {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [request, setRequest] = useState('');
  const [year, setYear] = useState(new Date().getFullYear());
  const schema = useSchemaFields('/api/finance/transactions');
  const entries = useQuery({
    queryKey: ['finance', 'transactions', year],
    queryFn: () => customInstance<Entry[]>({ url: '/api/finance/transactions', params: { year } }),
  });
  const trend = useQuery({ queryKey: ['finance', 'trends', year], queryFn: () => customInstance<Trend>({ url: `/api/finance/trends/${year}` }) });
  const observe = useMutation({ mutationFn: () => customInstance({ url: '/api/finance/observed-valuations', method: 'POST' }) });
  return (
    <PageContainer className='space-y-4'>
      <PageHeader
        title='거래와 재무 변화'
        description='거래 발생 시점과 입력 시점을 구별해 누적합니다. 거래 기록 후 실제 잔액·수량은 별도로 확인하세요.'
        actions={
          <Button asChild>
            <Link href='/finance'>포트폴리오</Link>
          </Button>
        }
      />
      <Alert>이체·매매·상환을 수입이나 자산 증가로 합산하지 않습니다. 기록된 현금흐름과 월별 자산 차이만으로 투자 수익을 단정하지 않습니다.</Alert>
      {(entries.error || schema.error || trend.error || observe.error) && (
        <Alert variant='destructive'>{(entries.error ?? schema.error ?? trend.error ?? observe.error)?.message}</Alert>
      )}
      <div className='flex flex-wrap gap-2'>
        <Button
          onClick={() => {
            setRequest(crypto.randomUUID());
            setOpen(true);
          }}>
          거래 기록
        </Button>
        <Button disabled={observe.isPending} onClick={() => observe.mutate()}>
          오늘의 관측 평가 보존
        </Button>
        <label>
          조회 연도{' '}
          <input className='rounded border p-2' type='number' min='1900' max='9998' value={year} onChange={e => setYear(Number(e.target.value))} />
        </label>
        <Button asChild>
          <Link href='/finance/history'>월마감·이력</Link>
        </Button>
      </div>
      {observe.isSuccess && <Alert>현재 관측 평가를 저장했습니다. 확정 월말 종가 기록과 구분해 보존합니다.</Alert>}
      {open && schema.data && (
        <Card>
          <CardContent>
            <DataForm
              fields={schema.data}
              labels={labels}
              enumLabels={kinds}
              current={{ request_id: request, currency: 'KRW' }}
              submitLabel='로컬 거래 기록'
              onCancel={() => setOpen(false)}
              onSubmit={async data => {
                await customInstance({ url: '/api/finance/transactions', method: 'POST', data });
                setOpen(false);
                await client.invalidateQueries({ queryKey: ['finance'] });
              }}
            />
          </CardContent>
        </Card>
      )}
      {trend.data && (
        <Card>
          <CardContent className='space-y-2'>
            <p className='font-semibold'>{year}년 기록된 현금흐름</p>
            {Object.entries(trend.data.cashflow_by_currency).map(([currency, amount]) => (
              <p key={currency}>
                {currency} 수입 {money(amount.income, currency)} · 지출 {money(amount.expense, currency)} · 차이{' '}
                {money(amount.net_cashflow, currency)}
              </p>
            ))}
            <p className='text-sm text-muted-foreground'>기록 범위는 불완전할 수 있습니다. 서로 다른 통화를 임의 환율로 합산하지 않습니다.</p>
          </CardContent>
        </Card>
      )}
      <div className='space-y-2'>
        {entries.data?.map(entry => (
          <Card key={entry.id}>
            <CardContent>
              <p className='font-semibold'>
                #{entry.id} {kinds[entry.kind] ?? entry.kind} · {money(entry.amount, entry.currency)}
              </p>
              <p>
                거래 {timestamp(entry.occurred_at)} · 입력 {timestamp(entry.recorded_at)}
              </p>
              <p className='text-sm'>
                근거: {entry.source} {entry.note}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
      <FinanceImport />
    </PageContainer>
  );
}
