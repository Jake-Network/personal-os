'use client';

import { type ReactNode, useState } from 'react';

import Link from 'next/link';

import { ArrowRight, CalendarClock, CheckCircle2, ChevronRight, Inbox, ListTodo, Repeat, TriangleAlert, Wallet } from 'lucide-react';


import { useRecurringDue } from '@/api-client/generated/portfolio/portfolio';
import { useSummary } from '@/api-client/generated/dashboard/dashboard';
import { EmptyState } from '@/components/empty-state';
import { PageContainer, Section } from '@/components/page-container';
import { QualityBadge } from '@/components/quality-badge';
import { QueryStatus } from '@/components/query-status';
import { Skeleton } from '@/components/skeleton';
import { StatusBadge } from '@/components/status-badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { dateOnly, dateTime, dayLabel, moneyShort, relative, timeOnly } from '@/lib/utils/format';
import { formatDuration } from '@/lib/utils/duration';
import { cn } from '@/lib/utils';
import { addDays, todayKey, zonedDayKey } from '@/lib/utils/zoned';

import { BalanceCheckInSheet } from '@/features/finance/balance-check-in';
import { CashflowImportDialog } from '@/features/finance/cashflow-import-dialog';
import { OnboardingGuide } from '@/features/onboarding/onboarding-guide';
import { useReviewCounts } from '@/features/review/review-view';

import { recordHref } from '@/features/personal-data/hooks/use-record-param';

import type { DashboardData, DashboardRunway } from '@/api-client/model';

const refId = (ref: unknown) => (typeof ref === 'string' ? ref.slice(ref.lastIndexOf(':') + 1) : '');

function runwaySub(runway: DashboardRunway | null | undefined): string {
  if (runway?.available && runway.months) return `월 지출 기준 약 ${runway.months}개월${runway.understated ? ' (일부 계좌 환산 불가)' : ''}`;
  if (runway?.available) return '지출이 수입 이하';
  if (runway?.reason === 'monthly_expense_insufficient_coverage') return '최근 3개월 지출 기록이 부족해 기간을 계산하지 않음';
  if (runway?.reason === 'spendable_liquidity_unknown') return '현금성 계좌 잔액이 필요합니다';
  return '월 지출 기록이 필요합니다';
}

type Tone = 'default' | 'warning' | 'destructive';
const toneClass = (tone: Tone) => (tone === 'warning' ? 'text-warning' : tone === 'destructive' ? 'text-destructive' : 'text-primary');

/** One thing to do now: a link, or a button that opens the quick action in place. */
function AttentionItem({ href, onClick, icon: Icon, tone = 'default', children }: { href?: string; onClick?: () => void; icon: typeof Inbox; tone?: Tone; children: ReactNode }) {
  const className = 'flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
  const content = (
    <>
      <Icon className={cn('size-4 shrink-0', toneClass(tone))} aria-hidden />
      <span className='flex-1'>{children}</span>
      <ChevronRight className='size-4 text-faint' aria-hidden />
    </>
  );
  return (
    <li>
      {href ? (
        <Link href={href} className={className}>
          {content}
        </Link>
      ) : (
        <button type='button' className={className} onClick={onClick}>
          {content}
        </button>
      )}
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
  const summary = useSummary();
  const review = useReviewCounts();
  const recurring = useRecurringDue().data ?? [];
  const [checkingIn, setCheckingIn] = useState(false);
  const [importing, setImporting] = useState(false);
  const [guideOpen, setGuideOpen] = useState<boolean | undefined>(undefined);
  const data = summary.data;
  const today = todayKey();

  const d: DashboardData = data?.data ?? {};
  const accounts = d.get_accounts_summary;
  const worth = accounts?.computed?.net_worth;
  const expense = d.get_cashflow_summary?.monthly_expense;
  const apps = d.get_job_applications?.applications ?? [];
  const interviews = d.get_interview_schedule?.interviews ?? [];
  const events = d.get_calendar_events?.events ?? [];
  const conflicts = d.get_calendar_events?.conflicts ?? [];
  const tasks = d.get_tasks?.open_tasks ?? [];
  const goals = d.get_goals?.active_goals ?? [];
  const health = d.get_health_summary;
  const flags = data?.data_quality_flags ?? [];
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
    ...tasks.flatMap(t => (t.due_on ? [{ day: t.due_on, time: null, title: t.title, kind: '할 일', href: recordHref('/plan/tasks', refId(t.ref)), overdue: t.overdue }] : [])),
  ]
    .filter(e => e.day >= today && e.day < weekEnd)
    .sort((a, b) => a.day.localeCompare(b.day) || String(a.time ?? '').localeCompare(String(b.time ?? '')));
  const todayCount = agenda.filter(a => a.day === today && a.kind !== '할 일').length;
  const agendaDays = [...new Set(agenda.map(a => a.day))];

  const flagCodes = new Set(flags.map(f => f.code));
  const unrecorded = recurring.filter(r => !r.recorded && r.scheduled_on <= today);
  const interviewsToday = agenda.filter(a => a.day === today && a.kind === '면접').length;
  // Today's short list: what has a deadline or goes stale, each with the action that fixes it.
  const todayItems = [
    overdue.length > 0 && (
      <AttentionItem key='overdue' href='/plan/tasks' icon={ListTodo} tone='destructive'>
        마감이 지난 할 일 <strong>{overdue.length}개</strong>
      </AttentionItem>
    ),
    todayCount > 0 && (
      <AttentionItem key='today' href='/plan' icon={CalendarClock}>
        오늘 {interviewsToday > 0 ? `면접 ${interviewsToday}건 포함 ` : ''}일정 <strong>{todayCount}건</strong>
        {conflicts.length > 0 && <span className='text-warning'> · 겹치는 일정 {conflicts.length}건</span>}
      </AttentionItem>
    ),
    unrecorded.length > 0 && (
      <AttentionItem key='recurring' href='/finance/cashflow' icon={Repeat}>
        기록하지 않은 반복 거래 <strong>{unrecorded.length}건</strong> · {unrecorded.map(r => r.name).slice(0, 2).join(', ')}
      </AttentionItem>
    ),
    (flagCodes.has('stale_balance') || flagCodes.has('spendable_liquidity_unknown')) && worth && (
      <AttentionItem key='balance' onClick={() => setCheckingIn(true)} icon={Wallet} tone='warning'>
        오래된 잔고가 있습니다 · <strong>한 번에 업데이트</strong>
      </AttentionItem>
    ),
    (flagCodes.has('monthly_expense_insufficient_coverage') || flagCodes.has('monthly_expense_unknown')) && (
      <AttentionItem key='expense' onClick={() => setImporting(true)} icon={TriangleAlert} tone='warning'>
        최근 3개월 지출 기록이 부족합니다 · <strong>은행·카드 내역 가져오기</strong>
      </AttentionItem>
    ),
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
          <Section title='오늘' count={todayItems.length || undefined}>
            {todayItems.length ? (
              <ul className='-mx-2'>{todayItems.slice(0, 4)}</ul>
            ) : (
              <p className='flex items-center gap-2 py-2 text-ui text-muted-foreground'>
                <CheckCircle2 className='size-4 text-success' aria-hidden /> 지금 처리할 항목이 없습니다.
              </p>
            )}
            {review.total > 0 && (
              <Link href='/review' className='mt-1 flex items-center gap-2 rounded-md px-0 py-1.5 text-ui text-muted-foreground hover:text-foreground'>
                <Inbox className='size-4' aria-hidden />
                검토함 <strong className='text-foreground'>{review.total}건</strong>
                <span className='text-xs text-faint'>
                  {[review.approvals && `승인 ${review.approvals}`, review.decisions && `회고 ${review.decisions}`, review.inbox && `알림 ${review.inbox}`]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
                <ChevronRight className='size-4 text-faint' aria-hidden />
              </Link>
            )}
          </Section>
          {!Object.values(data.checklist).every(Boolean) && (
            <Section
              title='상담 준비'
              actions={
                <Button size='sm' variant='ghost' onClick={() => setGuideOpen(true)}>
                  시작 가이드
                </Button>
              }>
              <ul className='flex flex-wrap gap-x-5 gap-y-2 text-ui'>
                {([
                  [data.checklist.ai_configuration_complete, '/settings/ai-provider', 'AI 연결'],
                  [data.checklist.has_cash_account, '/finance/accounts', '현금 계좌'],
                  [data.checklist.has_recent_expense, '/finance/cashflow', '최근 30일 지출'],
                  [data.checklist.has_active_application_or_goal, '/plan/goals', '목표 또는 지원'],
                ] as const).map(([complete, href, label]) => (
                  <li key={label}>
                    <Link href={href} className='flex items-center gap-1.5 hover:underline'>
                      <CheckCircle2 className={cn('size-4', complete ? 'text-success' : 'text-faint')} aria-hidden />
                      <span className={complete ? 'text-muted-foreground' : undefined}>{label}</span>
                      <span className='sr-only'>{complete ? '완료' : '준비 필요'}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Section>
          )}
          <OnboardingGuide
            checklist={data.checklist}
            open={guideOpen}
            onOpenChange={open => setGuideOpen(open ? true : undefined)}
          />
          <BalanceCheckInSheet open={checkingIn} onOpenChange={setCheckingIn} />
          <CashflowImportDialog open={importing} onOpenChange={setImporting} />
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
