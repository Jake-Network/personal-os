'use client';

/* eslint-disable @typescript-eslint/no-explicit-any -- dashboard summary rows are untyped tool outputs */
import type { ReactNode } from 'react';

import Link from 'next/link';

import { ArrowRight, Bell, CalendarClock, CheckCircle2, ChevronRight, Inbox, ListTodo, Sparkles, TriangleAlert } from 'lucide-react';

import { useCountUnreadInbox } from '@/api-client/generated/agent/agent';
import { useListPendingPlaybookRevisions } from '@/api-client/generated/playbooks/playbooks';

import { useListDecisions, useListMemories } from '@/api-client/generated/memory/memory';
import { useListProposals } from '@/api-client/generated/proposals/proposals';
import { useSummary } from '@/api-client/generated/dashboard/dashboard';
import { EmptyState } from '@/components/empty-state';
import { PageContainer, Section } from '@/components/page-container';
import { QualityBadge } from '@/components/quality-badge';
import { QueryStatus } from '@/components/query-status';
import { Skeleton } from '@/components/skeleton';
import { StatusBadge } from '@/components/status-badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { flagText } from '@/lib/labels';
import { dateOnly, dateTime, dayLabel, moneyShort, relative, timeOnly } from '@/lib/utils/format';
import { formatDuration } from '@/lib/utils/duration';
import { cn } from '@/lib/utils';
import { addDays, todayKey, zonedDayKey } from '@/lib/utils/zoned';

import { isDecisionReviewDue } from '@/features/memory/review-due';

import { recordHref } from '@/features/personal-data/hooks/use-record-param';

import type { DashboardSummary } from '../types';

/** Where each data-quality problem is fixed. */
const FLAG_FIX: Record<string, string> = {
  no_accounts: '/finance/accounts',
  stale_balance: '/finance/accounts',
  net_worth_incomplete: '/finance',
  stale_price: '/finance/investments',
  missing_fx: '/finance/investments',
  monthly_expense_unknown: '/finance/cashflow',
  monthly_expense_insufficient_coverage: '/finance/cashflow',
  cashflow_mixed_sources: '/finance/cashflow',
  spendable_liquidity_unknown: '/finance/accounts',
};

const refId = (ref: unknown) => (typeof ref === 'string' ? ref.slice(ref.lastIndexOf(':') + 1) : '');

function runwaySub(runway: DashboardSummary['computed']['runway'] | undefined): string {
  if (runway?.available && runway.months) return `월 지출 기준 약 ${runway.months}개월${runway.understated ? ' (일부 계좌 환산 불가)' : ''}`;
  if (runway?.available) return '지출이 수입 이하';
  if (runway?.reason === 'monthly_expense_insufficient_coverage') return '최근 3개월 지출 기록이 부족해 기간을 계산하지 않음';
  if (runway?.reason === 'spendable_liquidity_unknown') return '현금성 계좌 잔액이 필요합니다';
  return '월 지출 기록이 필요합니다';
}

function AttentionItem({ href, icon: Icon, tone = 'default', children }: { href: string; icon: typeof Inbox; tone?: 'default' | 'warning' | 'destructive'; children: ReactNode }) {
  return (
    <li>
      <Link
        href={href}
        className='flex items-center gap-2.5 rounded-md px-2 py-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'>
        <Icon className={cn('size-4 shrink-0', tone === 'warning' ? 'text-warning' : tone === 'destructive' ? 'text-destructive' : 'text-primary')} aria-hidden />
        <span className='flex-1'>{children}</span>
        <ChevronRight className='size-4 text-faint' aria-hidden />
      </Link>
    </li>
  );
}

function Figure({ href, label, value, sub, flags }: { href: string; label: string; value: string; sub?: string; flags?: { code: string; detail?: string | null }[] }) {
  return (
    <Card className='relative flex flex-col gap-0.5 p-4 transition-colors hover:bg-muted/40'>
      <div className='flex items-center gap-2'>
        <Link href={href} className='text-xs text-muted-foreground after:absolute after:inset-0 hover:underline'>
          {label}
        </Link>
        {flags && flags.length > 0 && <QualityBadge flags={flags} className='relative z-10 ml-auto' />}
      </div>
      <div className='text-display font-bold tabular-nums tracking-tight'>{value}</div>
      {sub && <div className='text-xs text-faint'>{sub}</div>}
    </Card>
  );
}

interface AgendaEntry {
  day: string;
  time: string | null;
  title: string;
  kind: string;
  href: string;
  overdue?: boolean;
}

/** What needs attention now, the key figures, and the coming week. All values come from the backend summary; no LLM call. */
export function DashboardView() {
  const summary = useSummary({ query: { select: d => d as DashboardSummary } });
  const pending = useListProposals({ status: 'pending' }).data?.length ?? 0;
  const dueReviews = (useListDecisions().data ?? []).filter(d => isDecisionReviewDue(d)).length;
  const proposedMemories = useListMemories({ status: 'proposed' }).data?.length ?? 0;
  const proposedPlaybooks = useListPendingPlaybookRevisions().data?.length ?? 0;
  const unread = useCountUnreadInbox().data?.unread ?? 0;
  const data = summary.data;
  const today = todayKey();

  const d = data?.data ?? {};
  const accounts = d.get_accounts_summary;
  const worth = accounts?.computed?.net_worth;
  const expense = d.get_cashflow_summary?.monthly_expense;
  const apps: any[] = d.get_job_applications?.applications ?? [];
  const interviews: any[] = d.get_interview_schedule?.interviews ?? [];
  const events: any[] = d.get_calendar_events?.events ?? [];
  const conflicts: any[] = d.get_calendar_events?.conflicts ?? [];
  const tasks: any[] = d.get_tasks?.open_tasks ?? [];
  const goals: any[] = d.get_goals?.active_goals ?? [];
  const health = d.get_health_summary;
  const flags = data?.data_quality_flags ?? [];
  const fixable = flags.filter(f => FLAG_FIX[f.code]);
  const financeFlags = (codes: string[]) => flags.filter(f => codes.includes(f.code));

  const overdue = tasks.filter(t => t.overdue);
  const weekEnd = addDays(today, 7);
  const agenda: AgendaEntry[] = [
    ...interviews.map(i => ({ day: zonedDayKey(i.starts_at), time: i.starts_at, title: `${i.company} ${i.stage}`, kind: '면접', href: '/career' })),
    ...events.map(e => ({
      day: zonedDayKey(e.starts_at),
      time: e.all_day ? null : e.starts_at,
      title: e.title,
      kind: e.kind === 'interview' ? '면접' : '일정',
      href: recordHref('/plan/events', refId(e.ref)),
    })),
    ...tasks.filter(t => t.due_on).map(t => ({ day: t.due_on, time: null, title: t.title, kind: '할 일', href: recordHref('/plan/tasks', refId(t.ref)), overdue: t.overdue })),
  ]
    .filter(e => e.day >= today && e.day < weekEnd)
    .sort((a, b) => a.day.localeCompare(b.day) || String(a.time ?? '').localeCompare(String(b.time ?? '')));
  const todayCount = agenda.filter(a => a.day === today && a.kind !== '할 일').length;
  const agendaDays = [...new Set(agenda.map(a => a.day))];

  const attention = [
    unread > 0 && (
      <AttentionItem key='inbox' href='/inbox' icon={Bell}>
        새 알림 <strong>{unread}건</strong>
      </AttentionItem>
    ),
    pending > 0 && (
      <AttentionItem key='p' href='/approvals' icon={Inbox}>
        승인을 기다리는 제안 <strong>{pending}건</strong>
      </AttentionItem>
    ),
    dueReviews > 0 && (
      <AttentionItem key='reviews' href='/reflect' icon={CalendarClock}>
        회고할 결정 <strong>{dueReviews}건</strong>
      </AttentionItem>
    ),
    proposedMemories > 0 && (
      <AttentionItem key='m' href='/settings/memory' icon={Sparkles}>
        확인이 필요한 기억 <strong>{proposedMemories}건</strong>
      </AttentionItem>
    ),
    proposedPlaybooks > 0 && (
      <AttentionItem key='pb' href='/approvals' icon={Sparkles}>
        상담에서 배운 절차 제안 <strong>{proposedPlaybooks}건</strong>
      </AttentionItem>
    ),
    overdue.length > 0 && (
      <AttentionItem key='o' href='/plan/tasks' icon={ListTodo} tone='destructive'>
        마감이 지난 할 일 <strong>{overdue.length}개</strong>
      </AttentionItem>
    ),
    todayCount > 0 && (
      <AttentionItem key='t' href='/plan' icon={CalendarClock}>
        오늘 일정 <strong>{todayCount}건</strong>
        {conflicts.length > 0 && <span className='text-warning'> · 겹치는 일정 {conflicts.length}건</span>}
      </AttentionItem>
    ),
    ...fixable.slice(0, 4).map((f, i) => (
      <AttentionItem key={`f${i}`} href={FLAG_FIX[f.code]} icon={TriangleAlert} tone='warning'>
        {flagText(f.code)}
      </AttentionItem>
    )),
  ].filter(Boolean);

  return (
    <PageContainer>
      <div className='mb-5 flex flex-col items-start justify-between gap-3 md:flex-row md:items-end'>
        <div>
          <h1 className='text-xl font-bold tracking-tight'>{dayLabel(today)}</h1>
          <p className='mt-0.5 text-xs text-faint'>{data ? `${dateTime(data.generated_at)} 기준` : ' '}</p>
        </div>
        <Button asChild variant='primary'>
          <Link href='/advisor'>
            상담하기 <ArrowRight />
          </Link>
        </Button>
      </div>

      <QueryStatus pending={false} error={summary.error} retry={summary.refetch} label='요약' />

      {summary.isPending && (
        <div className='grid grid-cols-1 gap-3 md:grid-cols-3' role='status'>
          <span className='sr-only'>불러오는 중</span>
          {[0, 1, 2].map(i => (
            <Skeleton key={i} className='h-24' />
          ))}
        </div>
      )}

      {data && (
        <>
          <Section title='확인 필요' count={attention.length || undefined}>
            {attention.length ? (
              <ul className='-mx-2'>{attention}</ul>
            ) : (
              <p className='flex items-center gap-2 py-2 text-ui text-muted-foreground'>
                <CheckCircle2 className='size-4 text-success' aria-hidden /> 지금 확인할 항목이 없습니다.
              </p>
            )}
          </Section>

          {!Object.values(data.checklist).every(Boolean) && (
            <Section title='상담 준비 체크리스트'>
              <ul className='space-y-2 text-ui'>
                {([
                  [data.checklist.ai_configuration_complete, '/settings/ai-provider', '선택한 AI 연결 설정 완료'],
                  [data.checklist.has_cash_account, '/finance/accounts', '현금 종류 계좌 등록'],
                  [data.checklist.has_recent_expense, '/finance/cashflow', '최근 30일 지출 기록'],
                  [data.checklist.has_active_application_or_goal, '/plan/goals', '진행 중 지원 또는 목표 등록'],
                ] as const).map(([complete, href, label]) => (
                  <li key={label}><Link href={href} className='flex items-center gap-2 hover:underline'>
                    <CheckCircle2 className={cn('size-4', complete ? 'text-success' : 'text-faint')} aria-hidden />
                    <span>{label}</span><span className='text-xs text-faint'>{complete ? '완료' : '준비 필요'}</span>
                  </Link></li>
                ))}
              </ul>
              <p className='mt-2 text-xs text-faint'>AI 연결 설정 완료는 실제 답변 생성 성공을 의미하지 않습니다.</p>
            </Section>
          )}
          {data.signals.length > 0 && (
            <Section title='이번 주 살펴볼 것'>
              <ul className='divide-y'>
                {data.signals.map(signal => (
                  <li key={signal.kind} className='flex flex-wrap items-center justify-between gap-2 py-2'>
                    <span>{signal.kind === 'expenses' ? '이번 달 누적 지출이 최근 3개월 월평균을 넘었습니다.'
                      : signal.kind === 'goals' ? `14일 안에 마감하는 목표 ${signal.count}개가 있습니다.`
                      : signal.kind === 'interviews' ? `7일 안에 면접 ${signal.count}건이 있습니다.`
                      : '최근 7일 동안 운동 기록이 없습니다.'}</span>
                    <Link href={`/advisor?briefing=${signal.kind}`} className='text-xs text-primary hover:underline'>상담으로 이어가기</Link>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <div className='mb-7 grid grid-cols-1 gap-3 md:grid-cols-3'>
            <Figure
              href='/finance'
              label='순자산'
              value={!worth ? '미기록' : worth.net_worth != null ? moneyShort(worth.net_worth) : '확인 필요'}
              sub={worth ? (worth.complete ? `자산 ${moneyShort(worth.total_assets)} · 부채 ${moneyShort(worth.total_liabilities)}` : '일부 항목 제외됨') : '계좌를 등록하면 계산합니다'}
              flags={financeFlags(['net_worth_incomplete', 'missing_fx', 'stale_balance', 'investment_excluded_from_net_worth', 'no_liabilities_recorded'])}
            />
            <Figure
              href='/finance/accounts'
              label='생활비로 쓸 수 있는 현금'
              value={worth?.spendable_liquidity != null ? moneyShort(worth.spendable_liquidity) : '미기록'}
              sub={runwaySub(data.computed?.runway)}
              flags={financeFlags(['spendable_liquidity_unknown'])}
            />
            <Figure
              href='/finance/cashflow'
              label='월평균 지출'
              value={expense?.available ? moneyShort(expense.monthly_average) : '미기록'}
              sub={
                expense?.available
                  ? `최근 ${expense.months_considered}개월`
                  : expense?.reason === 'insufficient_coverage'
                    ? `기록 부족 (${expense.months_with_data}/${expense.months_considered}개월)`
                    : '수입·지출을 기록하면 계산합니다'
              }
              flags={financeFlags(['monthly_expense_unknown', 'monthly_expense_insufficient_coverage', 'cashflow_foreign_currency_ignored', 'cashflow_mixed_sources'])}
            />
          </div>

          <div className='grid grid-cols-1 gap-x-8 lg:grid-cols-2'>
            <Section
              title='이번 주'
              actions={
                <Link href='/plan' className='text-xs text-primary hover:underline'>
                  달력
                </Link>
              }>
              {agendaDays.length === 0 ? (
                <EmptyState
                  className='py-5'
                  action={
                    <Button asChild size='sm'>
                      <Link href='/plan'>달력에서 추가</Link>
                    </Button>
                  }>
                  앞으로 7일 동안 일정과 마감이 없습니다.
                </EmptyState>
              ) : (
                <ol>
                  {agendaDays.map(day => (
                    <li key={day} className='flex gap-3 border-b py-2 last:border-b-0'>
                      <span className={cn('w-20 shrink-0 text-xs text-faint', day === today && 'font-semibold text-primary')}>
                        {day === today ? '오늘' : dayLabel(day).replace(/^\d+월 /, '')}
                      </span>
                      <ul className='flex min-w-0 flex-1 flex-col gap-1'>
                        {agenda
                          .filter(a => a.day === day)
                          .map((a, i) => (
                            <li key={i} className='flex items-baseline gap-2'>
                              <span className='w-16 shrink-0 text-xs tabular-nums text-muted-foreground'>{a.time ? timeOnly(a.time) : a.kind === '할 일' ? '마감' : '종일'}</span>
                              <Link href={a.href} className={cn('min-w-0 flex-1 truncate hover:underline', a.overdue && 'text-destructive')}>
                                {a.title}
                              </Link>
                              <span className='text-2xs text-faint'>{a.kind}</span>
                            </li>
                          ))}
                      </ul>
                    </li>
                  ))}
                </ol>
              )}
            </Section>

            <Section
              title='진행 중인 채용'
              count={apps.length || undefined}
              actions={
                <Link href='/career' className='text-xs text-primary hover:underline'>
                  전체
                </Link>
              }>
              {apps.length === 0 ? (
                <EmptyState className='py-5'>진행 중인 지원이 없습니다.</EmptyState>
              ) : (
                <ul>
                  {apps.slice(0, 6).map(a => (
                    <li key={a.ref} className='flex items-center gap-2 border-b py-2 last:border-b-0'>
                      <Link href={recordHref('/career', refId(a.ref))} className='min-w-0 flex-1 truncate hover:underline'>
                        <strong>{a.company}</strong> <span className='text-muted-foreground'>{a.role}</span>
                      </Link>
                      {a.next_step && <span className='hidden max-w-40 truncate text-xs text-faint sm:inline'>{a.next_step}</span>}
                      <StatusBadge value={a.status} />
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section
              title='목표'
              count={goals.length || undefined}
              actions={
                <Link href='/plan/goals' className='text-xs text-primary hover:underline'>
                  전체
                </Link>
              }>
              {goals.length === 0 ? (
                <EmptyState className='py-5'>진행 중인 목표가 없습니다.</EmptyState>
              ) : (
                <ul>
                  {goals.slice(0, 6).map(g => (
                    <li key={g.ref} className='flex items-center gap-2 border-b py-2 last:border-b-0'>
                      <Link href={recordHref('/plan/goals', refId(g.ref))} className='min-w-0 flex-1 truncate hover:underline'>
                        {g.title}
                      </Link>
                      {(g.current_value || g.target_value) && (
                        <span className='text-xs tabular-nums text-muted-foreground'>
                          {[g.current_value, g.target_value].filter(Boolean).join(' / ')}
                          {g.unit ? ` ${g.unit}` : ''}
                        </span>
                      )}
                      {g.target_date && <span className='text-xs text-faint'>{dateOnly(g.target_date)}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title='운동'>
              <Link href='/plan/workouts' className='flex items-center gap-2 py-2 text-ui hover:underline'>
                {health?.sessions ? (
                  <>
                    최근 4주 {health.sessions}회 · {formatDuration(health.total_seconds)} · 마지막 {relative(health.last_session_on)}
                  </>
                ) : (
                  <span className='text-muted-foreground'>최근 4주 동안 운동 기록이 없습니다</span>
                )}
                <ChevronRight className='size-4 text-faint' aria-hidden />
              </Link>
            </Section>
          </div>
        </>
      )}
    </PageContainer>
  );
}
