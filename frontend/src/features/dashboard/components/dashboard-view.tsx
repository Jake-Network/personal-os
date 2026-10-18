'use client';

/* eslint-disable @typescript-eslint/no-explicit-any -- dashboard summary rows are untyped tool outputs */
import { type ReactNode, useState } from 'react';

import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { EmptyState } from '@/components/empty-state';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table';

import { useSummary } from '@/api-client/generated/dashboard/dashboard';
import { flagDetail, flagText } from '@/lib/labels';
import { dateOnly, dateTime, money, moneyShort, relative } from '@/lib/utils/format';

import { AdvisorChat } from '@/features/advisor/components/advisor-chat';
import { enumLabel } from '@/features/personal-data/consts/resources';

import type { DashboardSummary } from '../types';
import { StatCard } from './stat-card';

const IMPORTANT_FLAGS = ['no_accounts', 'monthly_expense_unknown', 'net_worth_incomplete', 'stale_balance', 'stale_price', 'missing_fx', 'cashflow_mixed_sources'];

function Panel({ title, href, children }: { title: string; href: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <Link href={href} className='text-xs text-primary hover:underline'>
          관리
        </Link>
      </CardHeader>
      {children}
    </Card>
  );
}

function ListRow({ className, children }: { className?: string; children: ReactNode }) {
  return <li className={`flex items-baseline gap-2.5 border-b px-4 py-2 last:border-0 ${className ?? ''}`}>{children}</li>;
}

function runwaySub(runway: DashboardSummary['computed']['runway'] | undefined): string {
  if (runway?.available && runway.months) return `월 지출 기준 약 ${runway.months}개월${runway.understated ? ' (일부 계좌 환산 불가)' : ''}`;
  if (runway?.available) return '지출이 수입 이하';
  if (runway?.reason === 'monthly_expense_insufficient_coverage') return '최근 3개월 지출 기록이 부족해 계산하지 않음';
  if (runway?.reason === 'spendable_liquidity_unknown') return '현금 계좌와 잔액을 등록하세요';
  return '월 지출 데이터 없음';
}

export function DashboardView() {
  const { data, error, isPending } = useSummary({ query: { select: d => d as DashboardSummary } });
  const [panelConversation, setPanelConversation] = useState<number | null>(null);
  const router = useRouter();

  const d = data?.data ?? {};
  const accounts = d.get_accounts_summary;
  const worth = accounts?.computed?.net_worth;
  const cash = d.get_cashflow_summary;
  const portfolio = d.get_portfolio_summary;
  const apps: any[] = d.get_job_applications?.applications ?? [];
  const interviews: any[] = d.get_interview_schedule?.interviews ?? [];
  const events: any[] = d.get_calendar_events?.events ?? [];
  const conflicts: any[] = d.get_calendar_events?.conflicts ?? [];
  const tasks: any[] = d.get_tasks?.open_tasks ?? [];
  const goals: any[] = d.get_goals?.active_goals ?? [];
  const health = d.get_health_summary;

  const expense = cash?.monthly_expense;
  const runway = data?.computed?.runway;
  const importantFlags = (data?.data_quality_flags ?? []).filter(f => IMPORTANT_FLAGS.includes(f.code));
  const upcoming = [
    ...interviews.map(i => ({ t: i.starts_at as string, title: `${i.company} ${i.stage}`, tag: '면접' })),
    ...events.map(e => ({ t: e.starts_at as string, title: e.title as string, tag: enumLabel(e.kind) })),
  ]
    .filter(e => data && new Date(e.t).getTime() >= new Date(data.generated_at).getTime())
    .sort((a, b) => a.t.localeCompare(b.t))
    .slice(0, 7);

  return (
    <div className='grid h-full grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px]'>
      <div className='overflow-y-auto p-4 pb-12 md:px-7 md:pt-6'>
        <div className='mb-[18px] flex flex-col items-start justify-between gap-4 md:flex-row md:items-end'>
          <div>
            <h1 className='text-xl'>대시보드</h1>
            <p className='mt-1 text-muted-foreground'>{data ? `${dateTime(data.generated_at)} 기준 · 모든 수치는 백엔드 계산 결과입니다` : ' '}</p>
          </div>
          <Button asChild variant='primary'>
            <Link href='/advisor'>AI 상담 열기</Link>
          </Button>
        </div>

        {error && (
          <Alert variant='destructive' className='mb-3.5'>
            {error.message}
          </Alert>
        )}
        {isPending && <EmptyState>불러오는 중…</EmptyState>}

        {importantFlags.length > 0 && (
          <Alert variant='warning' className='mb-3.5'>
            <strong>데이터 확인 필요</strong>
            {importantFlags.slice(0, 3).map((f, i) => (
              <span key={i}>
                · {flagText(f.code)}
                {flagDetail(f.code, f.detail) ? ` (${flagDetail(f.code, f.detail)})` : ''}
              </span>
            ))}
          </Alert>
        )}

        {data && (
          <div className='flex flex-col gap-3.5'>
            <div className='grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-4'>
              <StatCard
                label='순자산'
                value={worth ? moneyShort(worth.net_worth) : '—'}
                sub={
                  worth
                    ? worth.complete
                      ? `자산 ${moneyShort(worth.total_assets)} · 부채 ${moneyShort(worth.total_liabilities)}`
                      : '일부 항목 제외됨'
                    : '계좌를 등록하세요'
                }
              />
              <StatCard
                label='생활비로 쓸 수 있는 현금'
                value={worth?.spendable_liquidity != null ? moneyShort(worth.spendable_liquidity) : '미기록'}
                sub={runwaySub(runway)}
              />
              <StatCard
                label='월평균 지출'
                value={expense?.available ? moneyShort(expense.monthly_average) : '—'}
                sub={
                  expense?.available
                    ? `최근 ${expense.months_considered}개월`
                    : expense?.reason === 'insufficient_coverage'
                      ? `기록 부족 (${expense.months_with_data}/${expense.months_considered}개월)`
                      : '수입·지출을 기록하세요'
                }
              />
              <StatCard
                label='투자 평가액'
                value={portfolio ? moneyShort(portfolio.computed.total_value_base) : '—'}
                sub={portfolio?.holdings?.length ? `상위 3종목 ${portfolio.computed.top3_concentration_pct}%` : '보유 종목 없음'}
              />
            </div>

            <div className='grid grid-cols-1 gap-3.5 md:grid-cols-2'>
              <Panel title='다가오는 일정' href='/data/calendar-events'>
                {conflicts.length > 0 && (
                  <Alert variant='warning' className='m-3'>
                    겹치는 일정 {conflicts.length}건이 있습니다
                  </Alert>
                )}
                <ul>
                  {upcoming.map((e, n) => (
                    <ListRow key={n}>
                      <span className='w-[120px] flex-none text-xs text-faint'>{dateTime(e.t)}</span>
                      <span className='flex-1'>{e.title}</span>
                      <Badge>{e.tag}</Badge>
                    </ListRow>
                  ))}
                  {upcoming.length === 0 && <ListRow className='text-xs text-faint'>예정된 일정이 없습니다</ListRow>}
                </ul>
              </Panel>

              <Panel title='진행 중인 채용' href='/data/job-applications'>
                <ul>
                  {apps.slice(0, 7).map(a => (
                    <ListRow key={a.ref}>
                      <span className='flex-1'>
                        <strong>{a.company}</strong> <span className='text-muted-foreground'>{a.role}</span>
                      </span>
                      <Badge variant='accent'>{enumLabel(a.status)}</Badge>
                    </ListRow>
                  ))}
                  {apps.length === 0 && <ListRow className='text-xs text-faint'>진행 중인 채용이 없습니다</ListRow>}
                </ul>
              </Panel>

              <Panel title='목표' href='/data/goals'>
                <ul>
                  {goals.slice(0, 6).map(g => (
                    <ListRow key={g.ref} className='block'>
                      <div className='flex items-center gap-2'>
                        <span className='flex-1'>{g.title}</span>
                        <span className='text-xs text-faint'>
                          {g.progress_pct ? `${g.progress_pct}%` : enumLabel(g.horizon)}
                          {g.target_date && ` · ${dateOnly(g.target_date)}`}
                        </span>
                      </div>
                      {g.progress_pct && (
                        <div className='mt-1.5 h-1.5 overflow-hidden rounded-sm bg-muted'>
                          <span className='block h-full bg-primary' style={{ width: `${Math.min(100, Number(g.progress_pct))}%` }} />
                        </div>
                      )}
                    </ListRow>
                  ))}
                  {goals.length === 0 && <ListRow className='text-xs text-faint'>진행 중인 목표가 없습니다</ListRow>}
                </ul>
              </Panel>

              <Panel title='할 일' href='/data/tasks'>
                <ul>
                  {tasks.slice(0, 7).map(t => (
                    <ListRow key={t.ref}>
                      <span className='flex-1'>{t.title}</span>
                      {t.overdue && <Badge variant='destructive'>지연</Badge>}
                      {t.priority === 'high' && <Badge variant='warning'>높음</Badge>}
                      <span className='text-xs text-faint'>{t.due_on ? dateOnly(t.due_on) : ''}</span>
                    </ListRow>
                  ))}
                  {tasks.length === 0 && <ListRow className='text-xs text-faint'>열린 할 일이 없습니다</ListRow>}
                </ul>
              </Panel>
            </div>

            <div className='grid grid-cols-1 gap-3.5 md:grid-cols-2'>
              <Panel title='계좌 · 부채' href='/data/accounts'>
                <Table>
                  <TableBody>
                    {(accounts?.accounts ?? []).map((a: any) => (
                      <TableRow key={a.ref}>
                        <TableCell>
                          {a.name}
                          <div className='text-xs text-faint'>{a.institution ?? enumLabel(a.kind)}</div>
                        </TableCell>
                        <TableCell className='text-right tabular-nums'>
                          {money(a.balance, a.currency)}
                          <div className='text-xs text-faint'>{relative(a.as_of)}</div>
                        </TableCell>
                      </TableRow>
                    ))}
                    {(accounts?.liabilities ?? []).map((l: any) => (
                      <TableRow key={l.ref}>
                        <TableCell>
                          {l.name}
                          <div className='text-xs text-faint'>부채 · {enumLabel(l.kind)}</div>
                        </TableCell>
                        <TableCell className='text-right tabular-nums text-destructive'>-{money(l.balance, l.currency)}</TableCell>
                      </TableRow>
                    ))}
                    {!accounts?.accounts?.length && !accounts?.liabilities?.length && (
                      <TableRow>
                        <TableCell className='text-xs text-faint'>등록된 계좌가 없습니다</TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </Panel>
              <Panel title='운동 (최근 4주)' href='/data/workout-logs'>
                <div className='grid grid-cols-1 gap-3.5 p-4 md:grid-cols-3'>
                  <StatCard label='횟수' value={`${health?.sessions ?? 0}회`} />
                  <StatCard label='총 시간' value={`${health?.total_minutes ?? 0}분`} />
                  <StatCard label='마지막 운동' value={health?.last_session_on ? relative(health.last_session_on) : '—'} />
                </div>
              </Panel>
            </div>
          </div>
        )}
      </div>

      <aside className='hidden min-h-0 flex-col border-l bg-card xl:flex'>
        <AdvisorChat
          key={panelConversation ?? 'new'}
          compact
          conversationId={panelConversation}
          onConversationCreated={setPanelConversation}
          header={
            <div className='flex items-center gap-2 border-b bg-card px-[18px] py-3'>
              <h2 className='flex-1 text-[15px]'>AI 어드바이저</h2>
              {panelConversation && (
                <>
                  <Button size='sm' onClick={() => router.push(`/advisor/${panelConversation}`)}>
                    크게 보기
                  </Button>
                  <Button size='sm' variant='ghost' onClick={() => setPanelConversation(null)}>
                    새 상담
                  </Button>
                </>
              )}
            </div>
          }
        />
      </aside>
    </div>
  );
}
