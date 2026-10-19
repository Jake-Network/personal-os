'use client';

import { useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { NotebookPen } from 'lucide-react';
import Link from 'next/link';

import { customInstance } from '@/api-client/custom-client';
import { errorMessage } from '@/api-client/api-error';
import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { todayKey } from '@/lib/utils/zoned';

import { recordHref } from '@/features/personal-data/hooks/use-record-param';

import { jobsKey } from './jobs-view';
import { periodRange, periodTitle, previousPeriod, type ReviewPeriod } from './period';

interface Review {
  id: number;
  status: string;
  period: string;
  start_on: string;
  end_on: string;
  content: string;
  evidence: { decision_ids?: number[]; outcome_ids?: number[] };
}
interface LinkedItem {
  id: number;
  title: string;
}

export const reviewsKey = ['period-reviews'] as const;
const PERIOD_LABEL: Record<ReviewPeriod, string> = { month: '월간', quarter: '분기', year: '연간' };

function ChipToggle({ items, value, onChange, label }: { items: LinkedItem[]; value: number[]; onChange: (v: number[]) => void; label: string }) {
  if (!items.length) return <p className='text-xs text-faint'>기록된 {label} 없음</p>;
  return (
    <div className='flex flex-wrap gap-1.5' role='group' aria-label={label}>
      {items.map(item => {
        const on = value.includes(item.id);
        return (
          <button
            key={item.id}
            type='button'
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter(v => v !== item.id) : [...value, item.id])}
            className={cn(
              'inline-flex h-7 items-center rounded-full border px-2.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              on ? 'border-primary bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-muted',
            )}>
            {item.title}
          </button>
        );
      })}
    </div>
  );
}

function ReviewCard({ review, decisions }: { review: Review; decisions: Map<number, string> }) {
  const cache = useQueryClient();
  const [content, setContent] = useState(review.content);
  const confirm = useMutation({
    mutationFn: () => customInstance({ method: 'POST', url: `/api/reviews/${review.id}/confirm`, data: { content } }),
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: reviewsKey });
      notify.success('회고를 확정했습니다');
    },
    onError: notify.error,
  });
  const decisionIds = review.evidence.decision_ids ?? [];
  const outcomeCount = review.evidence.outcome_ids?.length ?? 0;
  return (
    <article className='flex flex-col gap-2 border-b py-4 last:border-b-0'>
      <div className='flex flex-wrap items-center gap-2'>
        <h3 className='text-title font-semibold'>{periodTitle(review.period, review.start_on)} 회고</h3>
        {review.status === 'confirmed' ? <Badge variant='success'>확정</Badge> : <Badge variant='warning'>초안</Badge>}
      </div>
      {(decisionIds.length > 0 || outcomeCount > 0) && (
        <p className='flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground'>
          근거:
          {decisionIds.map(id => (
            <Link key={id} href={recordHref('/reflect', id)} className='text-primary hover:underline'>
              {decisions.get(id) ?? '결정 기록'}
            </Link>
          ))}
          {outcomeCount > 0 && <span>결과 회고 {outcomeCount}건</span>}
        </p>
      )}
      <Textarea
        aria-label={`${periodTitle(review.period, review.start_on)} 회고 내용`}
        className='min-h-32'
        value={content}
        readOnly={review.status === 'confirmed'}
        onChange={e => setContent(e.target.value)}
      />
      {review.status === 'draft' && (
        <div className='flex justify-end'>
          <Button variant='primary' disabled={confirm.isPending || !content.trim()} onClick={() => confirm.mutate()}>
            내용 확인 후 확정
          </Button>
        </div>
      )}
    </article>
  );
}

/** Draft a review of a finished month, quarter or year from recorded evidence, then confirm it. */
export function ReviewsView() {
  const cache = useQueryClient();
  const today = todayKey();
  const [period, setPeriod] = useState<ReviewPeriod>('month');
  const [pick, setPick] = useState(() => previousPeriod('month', today));
  const [background, setBackground] = useState(false);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [goalIds, setGoalIds] = useState<number[]>([]);
  const [projectIds, setProjectIds] = useState<number[]>([]);
  const goals = useQuery({ queryKey: ['review-goal-options'], queryFn: () => customInstance<LinkedItem[]>({ url: '/api/data/goals' }) });
  const projects = useQuery({ queryKey: ['review-project-options'], queryFn: () => customInstance<LinkedItem[]>({ url: '/api/career/records?kind=project' }) });
  const reviews = useQuery({ queryKey: reviewsKey, queryFn: () => customInstance<Review[]>({ url: '/api/reviews' }), refetchInterval: 15000 });
  const decisions = useQuery({ queryKey: ['review-decisions'], queryFn: () => customInstance<LinkedItem[]>({ url: '/api/decisions' }) });
  const decisionTitles = new Map((decisions.data ?? []).map(d => [d.id, d.title]));

  // A changed request is a new request; an unchanged retry reuses its ID so it is not created twice.
  const changed = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setRequestId(null);
  };
  const range = periodRange(period, pick.year, pick.index);
  const create = useMutation({
    mutationFn: () => {
      const stableId = requestId ?? crypto.randomUUID();
      setRequestId(stableId);
      return customInstance({
        method: 'POST',
        url: background ? '/api/jobs/period-review' : '/api/reviews',
        data: { request_id: stableId, period, ...range, goal_ids: goalIds, project_ids: projectIds, ...(background ? { enabled: true } : {}) },
      });
    },
    onSuccess: async () => {
      setRequestId(null);
      await Promise.all([cache.invalidateQueries({ queryKey: reviewsKey }), cache.invalidateQueries({ queryKey: jobsKey })]);
      notify.success(background ? '초안 작업을 예약했습니다. 진행 상황은 설정 › 자동 작업에서 볼 수 있습니다.' : '회고 초안을 만들었습니다');
    },
  });

  const thisYear = Number(today.slice(0, 4));
  const years = Array.from({ length: 10 }, (_, i) => thisYear - i);

  return (
    <div className='max-w-[860px]'>
      <Section title='새 회고 초안' info={<p>선택한 기간의 경력·결정·보존된 월말 재무 기록을 모아 초안을 만듭니다. 외부 AI를 호출하지 않습니다. 확정하기 전까지는 초안입니다.</p>}>
        <form
          className='flex flex-col gap-4 py-2'
          onSubmit={e => {
            e.preventDefault();
            create.mutate();
          }}>
          <div className='flex flex-wrap items-end gap-3'>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='review-period'>종류</Label>
              <NativeSelect
                id='review-period'
                value={period}
                onChange={e => {
                  const next = e.target.value as ReviewPeriod;
                  setPeriod(next);
                  setPick(previousPeriod(next, today));
                  setRequestId(null);
                }}>
                {Object.entries(PERIOD_LABEL).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='review-year'>연도</Label>
              <NativeSelect id='review-year' value={pick.year} onChange={e => changed(setPick)({ ...pick, year: Number(e.target.value) })}>
                {years.map(y => (
                  <option key={y} value={y}>
                    {y}년
                  </option>
                ))}
              </NativeSelect>
            </div>
            {period !== 'year' && (
              <div className='flex flex-col gap-1'>
                <Label htmlFor='review-index'>{period === 'month' ? '월' : '분기'}</Label>
                <NativeSelect id='review-index' value={pick.index} onChange={e => changed(setPick)({ ...pick, index: Number(e.target.value) })}>
                  {Array.from({ length: period === 'month' ? 12 : 4 }, (_, i) => i + 1).map(n => (
                    <option key={n} value={n}>
                      {period === 'month' ? `${n}월` : `${n}분기`}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            )}
            <span className='pb-1.5 text-ui text-muted-foreground'>{periodTitle(period, range.start_on)}</span>
          </div>
          <div className='flex flex-col gap-1.5'>
            <span className='text-ui font-medium'>함께 돌아볼 목표</span>
            <QueryStatus pending={goals.isPending} error={goals.error} retry={goals.refetch} label='목표' rows={1} />
            {goals.data && <ChipToggle label='목표' items={goals.data} value={goalIds} onChange={changed(setGoalIds)} />}
          </div>
          <div className='flex flex-col gap-1.5'>
            <span className='text-ui font-medium'>함께 돌아볼 프로젝트</span>
            <QueryStatus pending={projects.isPending} error={projects.error} retry={projects.refetch} label='프로젝트' rows={1} />
            {projects.data && <ChipToggle label='프로젝트' items={projects.data} value={projectIds} onChange={changed(setProjectIds)} />}
          </div>
          <label className='flex items-center gap-2'>
            <Checkbox checked={background} onCheckedChange={v => changed(setBackground)(v === true)} />
            백그라운드에서 만들기 (앱이 잠겨 있어도 한 번 실행)
          </label>
          {create.error && <Alert variant='destructive'>{errorMessage(create.error)}</Alert>}
          <div>
            <Button type='submit' variant='primary' disabled={create.isPending}>
              초안 만들기
            </Button>
          </div>
        </form>
      </Section>

      <Section
        title='기간 회고'
        count={reviews.data?.length}
        actions={
          <Link href='/settings/jobs' className='text-ui text-primary hover:underline'>
            자동 작업 보기
          </Link>
        }>
        <QueryStatus pending={reviews.isPending} error={reviews.error} retry={reviews.refetch} label='기간 회고' />
        {reviews.data?.length === 0 && (
          <EmptyState icon={NotebookPen} title='아직 기간 회고가 없습니다'>
            지난달부터 초안을 만들어 보세요.
          </EmptyState>
        )}
        {reviews.data?.map(review => (
          <ReviewCard key={`${review.id}-${review.status}`} review={review} decisions={decisionTitles} />
        ))}
      </Section>
    </div>
  );
}
