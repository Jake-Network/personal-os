'use client';

import type { ReactNode } from 'react';

import Link from 'next/link';

import { useQuery } from '@tanstack/react-query';
import { ChevronRight, Plus, RefreshCw, Wallet } from 'lucide-react';

import { useSummary } from '@/api-client/generated/dashboard/dashboard';
import { EmptyState } from '@/components/empty-state';
import { Section } from '@/components/page-container';
import { QualityBadge, type QualityFlag } from '@/components/quality-badge';
import { QueryStatus } from '@/components/query-status';
import { Button } from '@/components/ui/button';
import { dateOnly, money as formatMoney } from '@/lib/utils/format';
import { cn } from '@/lib/utils';

import type { DashboardRunway } from '@/api-client/model';
import { QuoteRefreshNotice, useQuoteRefresh } from '@/features/holdings/use-quote-refresh';

import { financeApi, type Portfolio } from './api';
import { PositionsTable } from './positions-table';
import { allocationPercent, issueFlags, money } from './presentation';

const SPENDABLE_FLAGS = [
  'spendable_liquidity_unknown',
  'monthly_expense_unknown',
  'monthly_expense_insufficient_coverage',
  'cashflow_mixed_sources',
  'stale_balance',
];

function runwayText(runway: DashboardRunway | null | undefined): string {
  if (runway?.available && runway.months) return `월평균 지출 기준 약 ${runway.months}개월${runway.understated ? ' (환산 못한 외화 계좌 제외)' : ''}`;
  if (runway?.available) return '지출이 수입보다 적습니다';
  if (runway?.reason === 'monthly_expense_insufficient_coverage') return '최근 3개월 지출 기록이 부족해 버틸 기간은 계산하지 않았습니다';
  if (runway?.reason === 'spendable_liquidity_unknown') return '현금성 계좌 잔액을 기록하면 계산합니다';
  return '지출 기록이 없어 버틸 기간은 계산하지 않았습니다';
}

function oldest(dates: (string | null | undefined)[]): string | null {
  const known = dates.filter((d): d is string => !!d).sort();
  return known[0] ?? null;
}

/** A headline figure that opens the tab where it is recorded. */
function Figure({
  label,
  value,
  sub,
  href,
  flags,
  flagLabel,
}: {
  label: string;
  value: string;
  sub: ReactNode;
  href: string;
  flags: QualityFlag[];
  flagLabel?: string;
}) {
  return (
    <div className='relative flex flex-col gap-1 rounded-lg border bg-card p-4 shadow-sm hover:border-primary/40'>
      <div className='flex items-center justify-between gap-2'>
        <Link
          href={href}
          className='text-ui text-muted-foreground after:absolute after:inset-0 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'>
          {label}
        </Link>
        <ChevronRight className='size-4 text-faint' aria-hidden />
      </div>
      <p className='text-display font-semibold tabular-nums'>{value}</p>
      <div className='text-xs text-muted-foreground'>{sub}</div>
      {flags.length > 0 && (
        // Above the card link so the details open instead of navigating.
        <div className='relative z-10 mt-1'>
          <QualityBadge flags={flags} label={flagLabel} />
        </div>
      )}
    </div>
  );
}

function Allocation({ data }: { data: Portfolio }) {
  const parts = [
    { label: '현금', value: data.cash, className: 'bg-primary' },
    { label: '투자', value: data.investments, className: 'bg-primary/55' },
    { label: '기타', value: data.allocation.other, className: 'bg-primary/25' },
  ];
  const known = data.total_assets != null;
  return (
    <Section title='자산 구성' info='총자산 대비 원화 평가액 비율입니다. 총자산이 확정되지 않으면 비율을 표시하지 않습니다.'>
      {known && (
        <div className='mb-3 flex h-2.5 overflow-hidden rounded-full bg-muted' aria-hidden>
          {parts.map(p => {
            // Bar width is display geometry only; the percentages shown are computed from Decimal strings.
            const pct = Number.parseFloat(allocationPercent(p.value, data.total_assets));
            return Number.isFinite(pct) && pct > 0 ? <span key={p.label} className={p.className} style={{ width: `${pct}%` }} /> : null;
          })}
        </div>
      )}
      <dl className='grid grid-cols-3 gap-3'>
        {parts.map(p => (
          <div key={p.label}>
            <dt className='flex items-center gap-1.5 text-xs text-muted-foreground'>
              <span className={cn('size-2 rounded-full', p.className)} aria-hidden />
              {p.label}
            </dt>
            <dd className='tabular-nums'>{money(p.value)}</dd>
            <dd className='text-xs text-faint'>{known ? allocationPercent(p.value, data.total_assets) : '비율 확인 필요'}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

export function PortfolioView() {
  const refresh = useQuoteRefresh();
  const portfolio = useQuery({ queryKey: ['finance', 'portfolio'], queryFn: financeApi.portfolio });
  const summary = useSummary();
  const data = portfolio.data;
  const worth = summary.data?.data.get_accounts_summary?.computed?.net_worth;
  const spendableFlags = (summary.data?.data_quality_flags ?? []).filter(f => SPENDABLE_FLAGS.includes(f.code));
  const holdingLines = data?.lines.filter(l => l.kind === 'holding') ?? [];

  return (
    <>
      <div className='mb-3 flex justify-end'>
        <Button variant='primary' disabled={refresh.isPending} onClick={() => refresh.mutate()}>
          <RefreshCw className={refresh.isPending ? 'animate-spin' : undefined} />
          {refresh.isPending ? '시세 확인 중…' : '시세 갱신'}
        </Button>
      </div>
      <QuoteRefreshNotice refresh={refresh} />
      <QueryStatus pending={portfolio.isPending} error={portfolio.error} retry={portfolio.refetch} label='자산 평가' rows={3} />
      {data && !data.lines.length && (
        <EmptyState
          icon={Wallet}
          title='아직 기록된 자산이 없습니다'
          action={
            <Button asChild variant='primary'>
              <Link href='/finance/accounts'>
                <Plus /> 계좌 추가
              </Link>
            </Button>
          }>
          계좌 잔액부터 기록하면 순자산과 생활비로 쓸 수 있는 현금을 계산합니다.
        </EmptyState>
      )}
      {data && data.lines.length > 0 && (
        <>
          <div className='mb-7 grid grid-cols-1 gap-3 md:grid-cols-3'>
            <Figure
              label='순자산'
              href='/finance/accounts'
              value={money(data.net_worth)}
              sub={
                <>
                  자산 {money(data.total_assets)} · 부채 {money(data.total_liabilities)}
                  {oldest(data.lines.map(l => l.as_of)) && (
                    <span className='block'>가장 오래된 기준일 {dateOnly(oldest(data.lines.map(l => l.as_of)))}</span>
                  )}
                </>
              }
              flags={issueFlags(data.issues)}
              flagLabel={data.complete ? '확인 필요' : '일부 제외'}
            />
            <Figure
              label='생활비로 쓸 수 있는 현금'
              href='/finance/accounts'
              value={summary.isPending ? '…' : formatMoney(worth?.spendable_liquidity)}
              sub={
                <>
                  {runwayText(summary.data?.computed.runway)}
                  <span className='block'>투자·연금·기타 자산은 포함하지 않습니다</span>
                </>
              }
              flags={spendableFlags}
            />
            <Figure
              label='투자 평가액'
              href='/finance/investments'
              value={money(data.investments)}
              sub={
                holdingLines.length ? (
                  <>
                    {holdingLines.length}개 종목
                    {oldest(holdingLines.map(l => l.price_as_of)) && ` · 가장 오래된 시세 ${dateOnly(oldest(holdingLines.map(l => l.price_as_of)))}`}
                  </>
                ) : (
                  '보유 종목 없음'
                )
              }
              flags={issueFlags(holdingLines.flatMap(l => l.issues.map(i => `${l.label}: ${i}`)))}
            />
          </div>
          <Allocation data={data} />
          <Section
            title='항목별 평가'
            count={data.lines.length}
            info={
              <>
                <p>이 컴퓨터에 기록된 값으로 평가합니다. Google은 시세 조회에만 쓰입니다.</p>
                <p>값이 없거나 확인되지 않은 항목은 0으로 계산하지 않고 합계에서 빼며, 그 경우 합계를 확정하지 않습니다.</p>
              </>
            }
            actions={
              <Button asChild size='sm' variant='ghost'>
                <Link href='/finance/history'>월별 기록</Link>
              </Button>
            }>
            <PositionsTable data={data} />
          </Section>
        </>
      )}
    </>
  );
}
