'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { customInstance } from '@/api-client/custom-client';
import { errorMessage } from '@/api-client/api-error';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

interface Review { id: number; status: string; period: string; start_on: string; end_on: string; content: string; evidence: { decision_ids?: number[]; outcome_ids?: number[] }; }
interface Job { id: number; status: string; enabled: boolean; attempts: number; max_attempts: number; last_error: string | null; result: { review_id?: number } | null; }
interface LinkedItem { id: number; title: string; }
interface Decision { id: number; title: string; expected_outcome: string | null; }
interface Outcome { id: number; actual_outcome: string; expected_outcome: string | null; reviewed_at: string | null; }
const labels: Record<string, string> = { draft: '초안', confirmed: '확정', pending: '대기', running: '실행 중', completed: '완료', cancelled: '허용 해제로 취소', failed: '실패' };

function ReviewCard({ review }: { review: Review }) {
  const cache = useQueryClient();
  const [content, setContent] = useState(review.content);
  const confirm = useMutation({
    mutationFn: () => customInstance({ method: 'POST', url: `/api/reviews/${review.id}/confirm`, data: { content } }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ['period-reviews'] }),
  });
  return <article className="space-y-3 rounded-lg border p-4">
    <h2 className="font-medium">{review.start_on} ~ {review.end_on} (종료일 제외) · {labels[review.status] ?? review.status}</h2>
    <p className="text-sm text-muted-foreground">결정 {review.evidence.decision_ids?.join(', ') || '없음'} · 결과 회고 {review.evidence.outcome_ids?.join(', ') || '없음'}</p>
    <label className="block text-sm">회고 내용<Textarea className="mt-1 min-h-32" value={content} disabled={review.status === 'confirmed'} onChange={e => setContent(e.target.value)} /></label>
    {review.status === 'draft' && <Button disabled={confirm.isPending || !content.trim()} onClick={() => confirm.mutate()}>내용 확인 후 확정</Button>}
    {confirm.error && <p role="alert" className="text-destructive">{errorMessage(confirm.error)}</p>}
  </article>;
}

function DecisionOutcomes({ decision }: { decision: Decision }) {
  const cache = useQueryClient();
  const [text, setText] = useState('');
  const outcomes = useQuery({ queryKey: ['decision-outcomes', decision.id], queryFn: () => customInstance<Outcome[]>({ url: `/api/decisions/${decision.id}/reviews` }) });
  const save = useMutation({
    mutationFn: () => customInstance({ method: 'POST', url: `/api/decisions/${decision.id}/reviews`, data: { actual_outcome: text } }),
    onSuccess: () => { setText(''); void cache.invalidateQueries({ queryKey: ['decision-outcomes', decision.id] }); },
  });
  return <article className="space-y-3 rounded-lg border p-4">
    <h3 className="font-medium">{decision.title}</h3>
    <p className="text-sm">기대 결과: {decision.expected_outcome || '미기록'}</p>
    {outcomes.data?.map(item => <p className="border-l-2 pl-3 text-sm" key={item.id}>{item.reviewed_at?.slice(0, 10) ?? '회고 시점 미기록'} · {item.actual_outcome}<br />당시 기대: {item.expected_outcome || '미기록'}</p>)}
    {outcomes.error && <p role="alert">{errorMessage(outcomes.error)}</p>}
    <label className="block text-sm">새 결과 회고<Textarea value={text} onChange={e => setText(e.target.value)} /></label>
    <Button disabled={!text.trim() || save.isPending} onClick={() => save.mutate()}>결과 추가</Button>
    {save.error && <p role="alert">{errorMessage(save.error)}</p>}
  </article>;
}

export function ReviewsView() {
  const cache = useQueryClient();
  const [period, setPeriod] = useState('month');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [schedule, setSchedule] = useState(false);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [goalIds, setGoalIds] = useState<number[]>([]);
  const [projectIds, setProjectIds] = useState<number[]>([]);
  const goals = useQuery({ queryKey: ['review-goal-options'], queryFn: () => customInstance<LinkedItem[]>({ url: '/api/data/goals' }) });
  const projects = useQuery({ queryKey: ['review-project-options'], queryFn: () => customInstance<LinkedItem[]>({ url: '/api/career/records?kind=project' }) });
  const reviews = useQuery({ queryKey: ['period-reviews'], queryFn: () => customInstance<Review[]>({ url: '/api/reviews' }), refetchInterval: 15000 });
  const jobs = useQuery({ queryKey: ['background-jobs'], queryFn: () => customInstance<Job[]>({ url: '/api/jobs' }), refetchInterval: 15000 });
  const decisions = useQuery({ queryKey: ['review-decisions'], queryFn: () => customInstance<Decision[]>({ url: '/api/decisions' }) });
  const create = useMutation({
    mutationFn: () => {
      const stableId = requestId ?? crypto.randomUUID();
      setRequestId(stableId);
      return customInstance({ method: 'POST', url: schedule ? '/api/jobs/period-review' : '/api/reviews', data: { request_id: stableId, period, start_on: start, end_on: end, goal_ids: goalIds, project_ids: projectIds, ...(schedule ? { enabled: true } : {}) } });
    },
    onSuccess: () => { setRequestId(null); void cache.invalidateQueries({ queryKey: ['period-reviews'] }); void cache.invalidateQueries({ queryKey: ['background-jobs'] }); },
  });
  const retry = useMutation({ mutationFn: (id: number) => customInstance({ method: 'POST', url: `/api/jobs/${id}/retry` }), onSuccess: () => cache.invalidateQueries({ queryKey: ['background-jobs'] }) });
  return <div className="mx-auto max-w-4xl space-y-6 p-4 md:p-8">
    <h1 className="text-2xl font-semibold">결정과 회고</h1>
    <p className="text-sm text-muted-foreground">기대와 실제 결과를 누적해 확인합니다. 기간 초안은 경력·결정·보존된 월말 재무 근거를 모으고, 외부 모델을 호출하지 않습니다.</p>
    <form className="space-y-3 rounded-lg border p-4" onSubmit={event => { event.preventDefault(); create.mutate(); }}>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">회고 종류<select className="mt-1 block w-full rounded border p-2" value={period} onChange={e => { setPeriod(e.target.value); setRequestId(null); }}><option value="month">월간</option><option value="quarter">분기</option><option value="year">연간</option></select></label>
        <label className="text-sm">시작일<Input required type="date" value={start} onChange={e => { setStart(e.target.value); setRequestId(null); }} /></label>
        <label className="text-sm">종료일 (제외)<Input required type="date" value={end} onChange={e => { setEnd(e.target.value); setRequestId(null); }} /></label>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">연결할 목표 (복수 선택)<select multiple className="mt-1 block w-full rounded border p-2" value={goalIds.map(String)} onChange={e => { setGoalIds(Array.from(e.target.selectedOptions, option => Number(option.value))); setRequestId(null); }}>{goals.data?.map(goal => <option key={goal.id} value={goal.id}>{goal.title}</option>)}</select></label>
        <label className="text-sm">연결할 프로젝트 (복수 선택)<select multiple className="mt-1 block w-full rounded border p-2" value={projectIds.map(String)} onChange={e => { setProjectIds(Array.from(e.target.selectedOptions, option => Number(option.value))); setRequestId(null); }}>{projects.data?.map(project => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label>
      </div>
      {(goals.error || projects.error) && <p role="alert">연결 대상 조회 실패: {errorMessage(goals.error || projects.error)}</p>}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={schedule} onChange={e => { setSchedule(e.target.checked); setRequestId(null); }} />앱 잠금 중에도 이 초안 생성 작업 실행 허용 (1회)</label>
      <Button type="submit" disabled={create.isPending}>초안 생성</Button>
      {create.error && <p role="alert" className="text-destructive">{errorMessage(create.error)}</p>}
    </form>
    {reviews.isLoading && <p>회고를 불러오는 중입니다.</p>}
    {reviews.error && <p role="alert">{errorMessage(reviews.error)}</p>}
    {reviews.data?.length === 0 && <p className="text-muted-foreground">아직 기간 회고가 없습니다.</p>}
    {reviews.data?.map(review => <ReviewCard key={review.id} review={review} />)}
    <h2 className="text-xl font-medium">백그라운드 작업</h2>
    {jobs.error && <p role="alert">{errorMessage(jobs.error)}</p>}
    {jobs.data?.length === 0 && <p className="text-sm text-muted-foreground">등록한 작업이 없습니다.</p>}
    {jobs.data?.map(job => <div key={job.id} className="flex flex-wrap items-center gap-3 rounded border p-3"><span>#{job.id} · {job.enabled ? labels[job.status] ?? job.status : '실행 미승인'} · 시도 {job.attempts}/{job.max_attempts}</span>{job.last_error && <span>처리 실패: {job.last_error}</span>}{job.status === 'failed' && <Button variant="default" disabled={retry.isPending} onClick={() => retry.mutate(job.id)}>재시도</Button>}</div>)}
    {retry.error && <p role="alert">{errorMessage(retry.error)}</p>}
    <h2 className="text-xl font-medium">결정별 결과</h2>
    {decisions.error && <p role="alert">{errorMessage(decisions.error)}</p>}
    {decisions.data?.length === 0 && <p className="text-sm text-muted-foreground">기억·의사결정 화면에서 먼저 결정을 기록하세요.</p>}
    {decisions.data?.map(decision => <DecisionOutcomes key={decision.id} decision={decision} />)}
  </div>;
}
