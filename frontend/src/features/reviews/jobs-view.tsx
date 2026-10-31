'use client';

import { useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import Link from 'next/link';

import { customInstance } from '@/api-client/custom-client';
import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Badge, type BadgeProps } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Switch } from '@/components/ui/switch';
import { dateTime } from '@/lib/utils/format';

import { BRIEFING_KINDS, BriefingSchedules } from './briefing-schedules';

interface Schedule {
  id: number;
  name: string;
  kind?: string;
  cadence: string;
  enabled: boolean;
  next_run_at: string;
}
export interface Job {
  id: number;
  kind: string;
  status: string;
  enabled: boolean;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  result: { review_id?: number; state?: string; playbook_revision_ids?: number[]; memory_ids?: number[] } | null;
  created_at: string;
  completed_at: string | null;
}

export const CADENCE_LABEL: Record<string, string> = { month: '매월', quarter: '분기마다', year: '매년' };
const KIND_LABEL: Record<string, string> = { period_review: '기간 회고 초안', market_quote_refresh: '시세 갱신', advisor_reflection: '상담에서 배우기' };
const JOB_ERROR: Record<string, string> = {
  interrupted: '앱이 실행 중 멈춰 AI 호출 결과가 확실하지 않습니다. 중복 호출을 막기 위해 자동으로 다시 실행하지 않았습니다.',
  attempts_exhausted: '재시도 한도에 도달했습니다.',
  invalid_structured_output: 'AI 응답 형식을 확인하지 못했습니다.',
  run_authorization_changed: 'AI 연결이나 앱 잠금 상태가 바뀌었습니다.',
};
const CANCELLED: Record<string, string> = {
  consent_revoked: '허용 해제로 취소',
  authorization_changed: '연결·잠금 변경으로 취소',
  source_deleted: '원본 상담이 삭제되어 취소',
};
const STATUS: Record<string, { label: string; tone: NonNullable<BadgeProps['variant']> }> = {
  pending: { label: '대기', tone: 'default' },
  running: { label: '실행 중', tone: 'accent' },
  completed: { label: '완료', tone: 'success' },
  cancelled: { label: '허용 해제로 취소', tone: 'default' },
  failed: { label: '실패', tone: 'destructive' },
};

export const jobsKey = ['background-jobs'] as const;

function NewSchedule({ open, onClose }: { open: boolean; onClose: () => void }) {
  const cache = useQueryClient();
  const [name, setName] = useState('정기 회고');
  const [cadence, setCadence] = useState('month');
  const [enabled, setEnabled] = useState(true);
  const create = useMutation({
    mutationFn: () => customInstance({ method: 'POST', url: '/api/jobs/schedules', data: { name, cadence, enabled } }),
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: ['job-schedules'] });
      notify.success('정기 회고를 추가했습니다');
      onClose();
    },
    onError: notify.error,
  });
  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent className='w-[min(420px,calc(100%-32px))]'>
        <DialogHeader>
          <DialogTitle>정기 회고 추가</DialogTitle>
        </DialogHeader>
        <form
          className='flex flex-col gap-3'
          onSubmit={e => {
            e.preventDefault();
            create.mutate();
          }}>
          <div className='flex flex-col gap-1'>
            <Label htmlFor='schedule-name'>이름</Label>
            <Input id='schedule-name' required maxLength={120} value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div className='flex flex-col gap-1'>
            <Label htmlFor='schedule-cadence'>주기</Label>
            <NativeSelect id='schedule-cadence' value={cadence} onChange={e => setCadence(e.target.value)}>
              {Object.entries(CADENCE_LABEL).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </NativeSelect>
          </div>
          <label className='flex items-center gap-2'>
            <Checkbox checked={enabled} onCheckedChange={v => setEnabled(v === true)} />
            바로 실행 허용
          </label>
          <div className='flex justify-end gap-2'>
            <Button type='button' onClick={onClose}>
              취소
            </Button>
            <Button type='submit' variant='primary' disabled={create.isPending}>
              추가
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Work the app runs on its own, only after you allow it. */
export function JobsView() {
  const cache = useQueryClient();
  const [adding, setAdding] = useState(false);
  const quoteConsent = useQuery({ queryKey: ['quote-refresh-consent'], queryFn: () => customInstance<{ enabled: boolean }>({ url: '/api/jobs/quote-refresh' }) });
  const schedules = useQuery({ queryKey: ['job-schedules'], queryFn: () => customInstance<Schedule[]>({ url: '/api/jobs/schedules' }) });
  const reviewSchedules = schedules.data?.filter(s => !BRIEFING_KINDS.includes(s.kind ?? 'period_review'));
  const jobs = useQuery({ queryKey: jobsKey, queryFn: () => customInstance<Job[]>({ url: '/api/jobs' }), refetchInterval: 15000 });
  const refreshJobs = () => cache.invalidateQueries({ queryKey: jobsKey });

  const setQuoteConsent = useMutation({
    mutationFn: (value: boolean) => customInstance({ method: 'PUT', url: '/api/jobs/quote-refresh', data: { enabled: value } }),
    onSuccess: () => Promise.all([cache.invalidateQueries({ queryKey: ['quote-refresh-consent'] }), refreshJobs()]),
    onError: notify.error,
  });
  const activate = useMutation({
    mutationFn: (schedule: Schedule) => customInstance({ method: 'PATCH', url: `/api/jobs/schedules/${schedule.id}`, data: { enabled: !schedule.enabled } }),
    onSuccess: () => Promise.all([cache.invalidateQueries({ queryKey: ['job-schedules'] }), refreshJobs()]),
    onError: notify.error,
  });
  const retry = useMutation({ mutationFn: (id: number) => customInstance({ method: 'POST', url: `/api/jobs/${id}/retry` }), onSuccess: refreshJobs, onError: notify.error });

  return (
    <div className='max-w-[860px]'>
      <Section
        title='시세 자동 갱신'
        info={<p>허용하면 약 5분마다 시세 전용 Google 파일을 갱신합니다. Google에는 거래소·티커·통화쌍만 보내며, 앱이 잠겨 있어도 실행합니다.</p>}>
        <QueryStatus pending={quoteConsent.isPending} error={quoteConsent.error} retry={quoteConsent.refetch} label='시세 갱신 설정' rows={1} />
        {quoteConsent.data && (
          <div className='flex items-center gap-3 py-2'>
            <div className='flex-1'>
              <p>보유 종목 시세를 자동으로 갱신</p>
              <p className='text-xs text-muted-foreground'>
                먼저{' '}
                <Link href='/settings/market' className='text-primary hover:underline'>
                  시세 연결
                </Link>
                을 설정하세요.
              </p>
            </div>
            <Switch
              aria-label='시세 자동 갱신 허용'
              checked={quoteConsent.data.enabled}
              disabled={setQuoteConsent.isPending}
              onCheckedChange={v => setQuoteConsent.mutate(v)}
            />
          </div>
        )}
      </Section>

      <Section
        title='정기 회고'
        count={reviewSchedules?.length}
        info={<p>완료된 달·분기·연도의 경력·결정·월말 재무 기록을 모아 회고 초안을 만듭니다. 외부 AI를 호출하지 않으며, 앱이 꺼져 있던 동안의 작업은 다시 켤 때 순서대로 처리합니다.</p>}
        actions={
          <Button size='sm' onClick={() => setAdding(true)}>
            <Plus /> 추가
          </Button>
        }>
        <QueryStatus pending={schedules.isPending} error={schedules.error} retry={schedules.refetch} label='정기 회고' rows={2} />
        {reviewSchedules?.length === 0 && <p className='py-2 text-ui text-muted-foreground'>등록한 정기 회고가 없습니다.</p>}
        <ul className='divide-y'>
          {reviewSchedules?.map(s => (
            <li key={s.id} className='flex items-center gap-3 py-2'>
              <div className='flex-1'>
                <p className='font-medium'>{s.name}</p>
                <p className='text-xs text-muted-foreground'>
                  {CADENCE_LABEL[s.cadence] ?? s.cadence} · {s.enabled ? `다음 실행 ${dateTime(s.next_run_at)}` : '실행 허용 안 됨'}
                </p>
              </div>
              <Switch aria-label={`${s.name} 실행 허용`} checked={s.enabled} disabled={activate.isPending} onCheckedChange={() => activate.mutate(s)} />
            </li>
          ))}
        </ul>
      </Section>

      <BriefingSchedules />

      <Section title='실행 내역'>
        <QueryStatus pending={jobs.isPending} error={jobs.error} retry={jobs.refetch} label='실행 내역' />
        {jobs.data?.length === 0 && <EmptyState>아직 실행된 작업이 없습니다.</EmptyState>}
        <ul className='divide-y'>
          {jobs.data?.map(job => {
            const base = STATUS[job.status] ?? { label: job.status, tone: 'default' as const };
            const cancelled = job.status === 'cancelled' && job.result?.state ? { ...base, label: CANCELLED[job.result.state] ?? base.label } : base;
            const status = job.enabled ? cancelled : { label: '실행 허용 안 됨', tone: 'warning' as const };
            return (
              <li key={job.id} className='flex flex-wrap items-center gap-x-3 gap-y-1 py-2'>
                <span className='font-medium'>{KIND_LABEL[job.kind] ?? '작업'}</span>
                <Badge variant={status.tone}>{status.label}</Badge>
                <span className='text-xs text-muted-foreground'>{dateTime(job.completed_at ?? job.created_at)}</span>
                {job.status === 'failed' && <span className='text-xs text-muted-foreground'>시도 {job.attempts}/{job.max_attempts}</span>}
                {!!(job.result?.playbook_revision_ids?.length || job.result?.memory_ids?.length) && (
                  <Link className='text-ui text-primary hover:underline' href='/review?view=approvals'>
                    제안 검토
                  </Link>
                )}
                {job.result?.review_id && (
                  <Link className='text-ui text-primary hover:underline' href='/reflect/reviews'>
                    회고 초안 보기
                  </Link>
                )}
                {job.status === 'failed' && (
                  <Button size='sm' className='ml-auto' disabled={retry.isPending} onClick={() => retry.mutate(job.id)}>
                    다시 시도
                  </Button>
                )}
                {job.last_error && job.status !== 'cancelled' && (
                  <p className='w-full text-xs text-destructive'>{JOB_ERROR[job.last_error] ?? '작업을 완료하지 못했습니다.'}</p>
                )}
              </li>
            );
          })}
        </ul>
      </Section>

      <NewSchedule open={adding} onClose={() => setAdding(false)} />
    </div>
  );
}
