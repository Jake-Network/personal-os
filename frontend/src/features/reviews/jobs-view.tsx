'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import Link from 'next/link';

import { customInstance } from '@/api-client/custom-client';
import { errorMessage } from '@/api-client/api-error';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface Schedule { id: number; name: string; cadence: string; enabled: boolean; next_run_at: string; }
interface Job { id: number; status: string; enabled: boolean; attempts: number; max_attempts: number; last_error: string | null; result: { review_id?: number } | null; }
const statuses: Record<string, string> = { pending: '대기', running: '실행 중', completed: '완료', cancelled: '허용 해제로 취소', failed: '실패' };

export function JobsView() {
  const cache = useQueryClient();
  const [name, setName] = useState('정기 회고');
  const [cadence, setCadence] = useState('month');
  const [enabled, setEnabled] = useState(false);
  const quoteConsent = useQuery({ queryKey: ['quote-refresh-consent'], queryFn: () => customInstance<{ enabled: boolean }>({ url: '/api/jobs/quote-refresh' }) });
  const setQuoteConsent = useMutation({ mutationFn: (value: boolean) => customInstance({ method: 'PUT', url: '/api/jobs/quote-refresh', data: { enabled: value } }), onSuccess: () => { void cache.invalidateQueries({ queryKey: ['quote-refresh-consent'] }); void cache.invalidateQueries({ queryKey: ['background-jobs'] }); } });
  const schedules = useQuery({ queryKey: ['job-schedules'], queryFn: () => customInstance<Schedule[]>({ url: '/api/jobs/schedules' }) });
  const jobs = useQuery({ queryKey: ['background-jobs'], queryFn: () => customInstance<Job[]>({ url: '/api/jobs' }), refetchInterval: 15000 });
  const create = useMutation({ mutationFn: () => customInstance({ method: 'POST', url: '/api/jobs/schedules', data: { name, cadence, enabled } }), onSuccess: () => cache.invalidateQueries({ queryKey: ['job-schedules'] }) });
  const activate = useMutation({ mutationFn: (schedule: Schedule) => customInstance({ method: 'PATCH', url: `/api/jobs/schedules/${schedule.id}`, data: { enabled: !schedule.enabled } }), onSuccess: () => { void cache.invalidateQueries({ queryKey: ['job-schedules'] }); void cache.invalidateQueries({ queryKey: ['background-jobs'] }); } });
  const retry = useMutation({ mutationFn: (id: number) => customInstance({ method: 'POST', url: `/api/jobs/${id}/retry` }), onSuccess: () => cache.invalidateQueries({ queryKey: ['background-jobs'] }) });
  return <div className="mx-auto max-w-4xl space-y-5 p-4 md:p-8">
    <h1 className="text-2xl font-semibold">백그라운드 작업</h1>
    <p className="text-sm text-muted-foreground">활성화한 회고는 앱 잠금 중에도 로컬에서 실행합니다. 외부 모델 호출 없이 완료된 달·분기·연도의 기록을 모아 초안을 만듭니다. 앱이 종료된 동안의 작업은 재시작 후 순서대로 처리합니다.</p>
    <section className="space-y-3 rounded-lg border p-4">
      <h2 className="font-medium">Google 시세 갱신</h2>
      <p className="text-sm text-muted-foreground">허용하면 약 5분 간격으로 시세 전용 파일을 갱신합니다. Google에는 거래소·티커·통화쌍만 전송하며, 앱 잠금 중에도 실행합니다. 시세 전용 연결을 먼저 설정하세요.</p>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={quoteConsent.data?.enabled ?? false} disabled={quoteConsent.isLoading || setQuoteConsent.isPending || !!quoteConsent.error} onChange={e => setQuoteConsent.mutate(e.target.checked)} />시세 자동 갱신 실행 허용</label>
      {(quoteConsent.error || setQuoteConsent.error) && <p role="alert">{errorMessage(quoteConsent.error || setQuoteConsent.error)}</p>}
    </section>
    <form className="space-y-3 rounded-lg border p-4" onSubmit={event => { event.preventDefault(); create.mutate(); }}>
      <label className="block text-sm">이름<Input required maxLength={120} value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="block text-sm">주기<select className="ml-3 rounded border p-2" value={cadence} onChange={e => setCadence(e.target.value)}><option value="month">매월</option><option value="quarter">분기마다</option><option value="year">매년</option></select></label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />이 주기 작업 실행을 허용합니다</label>
      <Button type="submit" disabled={create.isPending}>주기 작업 등록</Button>
      {create.error && <p role="alert">{errorMessage(create.error)}</p>}
    </form>
    {schedules.isLoading && <p>주기 작업을 불러오는 중입니다.</p>}
    {schedules.error && <p role="alert">{errorMessage(schedules.error)}</p>}
    {schedules.data?.length === 0 && <p>등록한 주기 작업이 없습니다.</p>}
    {schedules.data?.map(schedule => <article className="space-y-2 rounded border p-3" key={schedule.id}>
      <h2 className="font-medium">{schedule.name} · {schedule.enabled ? '활성' : '중지'}</h2>
      <p className="text-sm">다음 처리 기준: {schedule.next_run_at}</p>
      <Button disabled={activate.isPending} onClick={() => activate.mutate(schedule)}>{schedule.enabled ? '실행 허용 해제' : '실행 허용'}</Button>
    </article>)}
    {activate.error && <p role="alert">{errorMessage(activate.error)}</p>}
    <h2 className="text-xl font-medium">실행 내역</h2>
    {jobs.isLoading && <p>작업을 불러오는 중입니다.</p>}
    {jobs.error && <p role="alert">{errorMessage(jobs.error)}</p>}
    {jobs.data?.length === 0 && <p>실행 내역이 없습니다.</p>}
    {jobs.data?.map(job => <article className="flex flex-wrap items-center gap-3 rounded border p-3" key={job.id}>
      <span>#{job.id} · {job.enabled ? statuses[job.status] ?? job.status : '실행 미승인'} · 시도 {job.attempts}/{job.max_attempts}</span>
      {job.last_error && <span>실패: {job.last_error}</span>}
      {job.result?.review_id && <Link className="underline" href="/reviews">회고 초안 확인</Link>}
      {job.status === 'failed' && <Button disabled={retry.isPending} onClick={() => retry.mutate(job.id)}>재시도</Button>}
    </article>)}
    {retry.error && <p role="alert">{errorMessage(retry.error)}</p>}
  </div>;
}
