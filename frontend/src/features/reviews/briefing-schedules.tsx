'use client';

import { useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';

import { errorMessage } from '@/api-client/api-error';
import { getCountUnreadInboxQueryKey, getListInboxItemsQueryKey } from '@/api-client/generated/agent/agent';
import {
  getListJobSchedulesQueryKey,
  useActivateJobSchedule,
  useCreateBriefingSchedule,
  useListJobSchedules,
  useRunBriefingNow,
  useUpdateBriefingSchedule,
} from '@/api-client/generated/jobs/jobs';
import { useListPlaybooks } from '@/api-client/generated/playbooks/playbooks';
import type { BriefingCreate, Category, ScheduleItem } from '@/api-client/model';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Switch } from '@/components/ui/switch';
import { ALL_CATEGORIES, CATEGORY_LABEL } from '@/lib/labels';
import { dateTime } from '@/lib/utils/format';

export const BRIEFING_KINDS = ['daily_briefing', 'weekly_briefing'];
const WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일'];
const PAUSED: Record<string, string> = { authorization_changed: '연결·잠금·모델이 바뀌어 멈춤' };

interface Options {
  weekday?: number | null;
  llm_enabled?: boolean;
  categories?: string[];
  playbook_ids?: number[];
}

function BriefingDialog({ schedule, onClose }: { schedule: ScheduleItem | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const options = (schedule?.options ?? {}) as Options;
  const [form, setForm] = useState<BriefingCreate>({
    name: schedule?.name ?? '아침 브리핑',
    kind: (schedule?.kind as BriefingCreate['kind']) ?? 'daily_briefing',
    local_time: schedule?.local_time ?? '08:00',
    weekday: options.weekday ?? 0,
    llm_enabled: options.llm_enabled ?? false,
    categories: (options.categories ?? []) as Category[],
    playbook_ids: options.playbook_ids ?? [],
    enabled: schedule?.enabled ?? true,
  });
  const playbooks = useListPlaybooks();
  const done = async () => {
    await queryClient.invalidateQueries({ queryKey: getListJobSchedulesQueryKey() });
    notify.success('브리핑 예약을 저장했습니다');
    onClose();
  };
  const create = useCreateBriefingSchedule({ mutation: { onSuccess: done } });
  const update = useUpdateBriefingSchedule({ mutation: { onSuccess: done } });
  const busy = create.isPending || update.isPending;
  const error = create.error ?? update.error;
  const categories = form.categories ?? [];

  return (
    <Dialog open onOpenChange={open => !open && !busy && onClose()}>
      <DialogContent className='max-h-[90vh] w-[min(520px,calc(100%-32px))] overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{schedule ? '브리핑 예약 수정' : '브리핑 예약'}</DialogTitle>
        </DialogHeader>
        <form
          className='flex flex-col gap-3'
          onSubmit={event => {
            event.preventDefault();
            const data = { ...form, weekday: form.kind === 'weekly_briefing' ? form.weekday : null };
            if (schedule) update.mutate({ scheduleId: schedule.id, data });
            else create.mutate({ data });
          }}>
          <div className='flex flex-col gap-1'>
            <Label htmlFor='briefing-name'>이름</Label>
            <Input id='briefing-name' required maxLength={120} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className='grid grid-cols-2 gap-3'>
            <div className='flex flex-col gap-1'>
              <Label htmlFor='briefing-kind'>주기</Label>
              <NativeSelect id='briefing-kind' value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value as BriefingCreate['kind'] })}>
                <option value='daily_briefing'>매일</option>
                <option value='weekly_briefing'>매주</option>
              </NativeSelect>
            </div>
            {form.kind === 'weekly_briefing' && (
              <div className='flex flex-col gap-1'>
                <Label htmlFor='briefing-weekday'>요일</Label>
                <NativeSelect id='briefing-weekday' value={String(form.weekday ?? 0)} onChange={e => setForm({ ...form, weekday: Number(e.target.value) })}>
                  {WEEKDAYS.map((day, index) => (
                    <option key={day} value={index}>
                      {day}요일
                    </option>
                  ))}
                </NativeSelect>
              </div>
            )}
            <div className='flex flex-col gap-1'>
              <Label htmlFor='briefing-time'>시각</Label>
              <Input id='briefing-time' type='time' required value={form.local_time} onChange={e => setForm({ ...form, local_time: e.target.value })} />
            </div>
          </div>
          <label className='flex items-start gap-3 rounded-md border p-3'>
            <span className='flex-1'>
              <span className='block text-ui font-medium'>확인할 항목이 있으면 AI가 정리</span>
              <span className='block text-xs text-muted-foreground'>
                끄면 이 기기에서 계산한 항목만 알림으로 보여 줍니다. 켜면 항목이 있는 날에만 AI를 호출하고, 결과는 새 상담으로 남깁니다.
              </span>
            </span>
            <Switch checked={form.llm_enabled ?? false} onCheckedChange={value => setForm({ ...form, llm_enabled: value })} />
          </label>
          {form.llm_enabled && (
            <>
              <fieldset>
                <legend className='mb-1 text-ui font-medium'>AI에 보낼 영역</legend>
                <div className='flex flex-wrap gap-x-4 gap-y-1.5'>
                  {ALL_CATEGORIES.map(category => (
                    <label key={category} className='flex items-center gap-1.5 text-ui'>
                      <Checkbox
                        checked={categories.includes(category)}
                        onCheckedChange={checked =>
                          setForm({ ...form, categories: checked === true ? [...categories, category] : categories.filter(c => c !== category) })
                        }
                      />
                      {CATEGORY_LABEL[category]}
                    </label>
                  ))}
                </div>
                <p className='mt-1 text-2xs text-faint'>
                  아무것도 고르지 않으면 항목에 필요한 영역만 보냅니다. 데이터 공유 설정에서 막은 영역은 어느 경우에도 보내지 않습니다.
                </p>
              </fieldset>
              {!!playbooks.data?.length && (
                <div className='flex flex-col gap-1'>
                  <Label htmlFor='briefing-playbook'>함께 쓸 플레이북</Label>
                  <NativeSelect
                    id='briefing-playbook'
                    value={String(form.playbook_ids?.[0] ?? '')}
                    onChange={e => setForm({ ...form, playbook_ids: e.target.value ? [Number(e.target.value)] : [] })}>
                    <option value=''>없음</option>
                    {playbooks.data.map(p => (
                      <option key={p.id} value={p.id}>
                        {p.active_revision?.title ?? p.slug}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
              )}
            </>
          )}
          <label className='flex items-center gap-2'>
            <Checkbox checked={form.enabled ?? false} onCheckedChange={v => setForm({ ...form, enabled: v === true })} />
            바로 실행 허용
          </label>
          {form.llm_enabled && form.enabled && (
            <p className='text-2xs text-faint'>지금 연결된 AI 계정과 모델로 실행합니다. 연결이 바뀌면 예약을 멈추고 알려 드립니다.</p>
          )}
          {error && <Alert variant='destructive'>{errorMessage(error)}</Alert>}
          <div className='flex justify-end gap-2'>
            <Button type='button' disabled={busy} onClick={onClose}>
              취소
            </Button>
            <Button type='submit' variant='primary' disabled={busy}>
              저장
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Proactive briefings: local signals first; a model run only on days with something to report. */
export function BriefingSchedules() {
  const queryClient = useQueryClient();
  const schedules = useListJobSchedules();
  const [editing, setEditing] = useState<ScheduleItem | null | undefined>(undefined);
  const briefings = schedules.data?.filter(s => BRIEFING_KINDS.includes(s.kind ?? '')) ?? [];
  const refresh = () =>
    Promise.all(
      [getListJobSchedulesQueryKey(), ['job-schedules'], getListInboxItemsQueryKey(), getCountUnreadInboxQueryKey(), ['background-jobs']].map(queryKey =>
        queryClient.invalidateQueries({ queryKey }),
      ),
    );
  const activate = useActivateJobSchedule({ mutation: { onSuccess: refresh, onError: notify.error } });
  const runNow = useRunBriefingNow({
    mutation: {
      onSuccess: async result => {
        await refresh();
        const state = (result as { state?: string }).state;
        notify.success(
          state === 'silent'
            ? '지금 확인할 항목이 없습니다'
            : state === 'queued'
              ? '브리핑을 준비하고 있습니다. 알림에서 확인하세요'
              : state === 'paused'
                ? '연결이 바뀌어 예약을 멈췄습니다'
                : '확인할 항목을 알림에 표시했습니다',
        );
      },
      onError: notify.error,
    },
  });

  return (
    <Section
      title='브리핑'
      count={briefings.length}
      info={
        <p>
          정한 시각에 회고할 결정, 다가오는 면접·마감, 오래된 시세처럼 확인할 항목을 이 기기에서 먼저 계산합니다. 항목이 없으면 아무것도 하지 않습니다. AI 정리를 켠
          경우에만 새 상담으로 브리핑을 만들고, 제안은 승인 대기로 들어갑니다. 앱이 꺼져 있던 동안 놓친 날은 몰아서 실행하지 않습니다.
        </p>
      }
      actions={
        <Button size='sm' onClick={() => setEditing(null)}>
          <Plus /> 추가
        </Button>
      }>
      <QueryStatus pending={schedules.isPending} error={schedules.error} retry={schedules.refetch} label='브리핑' rows={1} />
      {schedules.isSuccess && briefings.length === 0 && <p className='py-2 text-ui text-muted-foreground'>예약한 브리핑이 없습니다.</p>}
      <ul className='divide-y'>
        {briefings.map(s => {
          const options = (s.options ?? {}) as Options;
          return (
            <li key={s.id} className='flex flex-wrap items-center gap-x-3 gap-y-1 py-2'>
              <div className='min-w-0 flex-1'>
                <p className='flex flex-wrap items-center gap-2 font-medium'>
                  {s.name}
                  {options.llm_enabled ? <Badge variant='accent'>AI 정리</Badge> : <Badge>알림만</Badge>}
                  {s.paused_reason && <Badge variant='warning'>{PAUSED[s.paused_reason] ?? '멈춤'}</Badge>}
                </p>
                <p className='text-xs text-muted-foreground'>
                  {s.kind === 'weekly_briefing' ? `매주 ${WEEKDAYS[options.weekday ?? 0]}요일` : '매일'} {s.local_time} ·{' '}
                  {s.enabled ? `다음 실행 ${dateTime(s.next_run_at)}` : '실행 허용 안 됨'}
                </p>
              </div>
              <Button size='sm' variant='ghost' disabled={runNow.isPending} onClick={() => runNow.mutate({ scheduleId: s.id, data: { request_id: crypto.randomUUID() } })}>
                지금 실행
              </Button>
              <Button size='sm' variant='ghost' onClick={() => setEditing(s)}>
                수정
              </Button>
              <Switch
                aria-label={`${s.name} 실행 허용`}
                checked={s.enabled}
                disabled={activate.isPending}
                onCheckedChange={value => activate.mutate({ scheduleId: s.id, data: { enabled: value } })}
              />
            </li>
          );
        })}
      </ul>
      {editing !== undefined && <BriefingDialog schedule={editing} onClose={() => setEditing(undefined)} />}
    </Section>
  );
}
