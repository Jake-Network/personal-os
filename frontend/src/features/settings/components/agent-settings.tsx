'use client';

import { useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';

import { errorMessage } from '@/api-client/api-error';
import { getGetAgentSettingsQueryKey, useGetAgentActivity, useGetAgentSettings, useUpdateAgentSettings } from '@/api-client/generated/agent/agent';
import type { AdvisorStyle, AgentSettingsView } from '@/api-client/model';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

import { FINDING_LABEL } from '@/features/playbooks/consts';

const TONE: Record<AdvisorStyle['tone'] & string, string> = { direct: '직설적으로', balanced: '차분하고 균형 있게', gentle: '부드럽게' };
const DETAIL: Record<AdvisorStyle['detail'] & string, string> = { brief: '핵심만 짧게', normal: '보통', thorough: '자세하게' };

function StyleForm({ settings }: { settings: AgentSettingsView }) {
  const queryClient = useQueryClient();
  const [style, setStyle] = useState<AdvisorStyle>(settings.style ?? {});
  const update = useUpdateAgentSettings({
    mutation: {
      onSuccess: data => {
        queryClient.setQueryData(getGetAgentSettingsQueryKey(), data);
        notify.success('상담 방식을 저장했습니다');
      },
    },
  });
  return (
    <form
      className='flex flex-col gap-3'
      onSubmit={event => {
        event.preventDefault();
        update.mutate({ data: { learning: settings.learning, style, recording: settings.recording } });
      }}>
      <div className='grid grid-cols-1 gap-3 md:grid-cols-2'>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='style-tone'>말투</Label>
          <NativeSelect id='style-tone' value={style.tone ?? 'balanced'} onChange={e => setStyle({ ...style, tone: e.target.value as AdvisorStyle['tone'] })}>
            {Object.entries(TONE).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='style-detail'>답변 길이</Label>
          <NativeSelect id='style-detail' value={style.detail ?? 'normal'} onChange={e => setStyle({ ...style, detail: e.target.value as AdvisorStyle['detail'] })}>
            {Object.entries(DETAIL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <label className='flex items-center gap-3'>
        <span className='flex-1 text-ui'>복잡한 상담도 결론부터</span>
        <Switch checked={style.answer_first ?? true} onCheckedChange={value => setStyle({ ...style, answer_first: value })} />
      </label>
      <div className='flex flex-col gap-1'>
        <Label htmlFor='style-custom'>추가로 바라는 점</Label>
        <Textarea
          id='style-custom'
          maxLength={500}
          rows={3}
          placeholder='예: 숫자는 표로 정리해 주세요'
          value={style.custom ?? ''}
          onChange={e => setStyle({ ...style, custom: e.target.value })}
        />
        <p className='text-2xs text-faint'>표현 방식만 바꿉니다. 근거·공유·승인 규칙은 그대로 적용됩니다.</p>
      </div>
      {settings.style_warnings?.length ? (
        <Alert>확인할 내용: {settings.style_warnings.map(w => FINDING_LABEL[w] ?? w).join(', ')}</Alert>
      ) : null}
      {update.error && <Alert variant='destructive'>{errorMessage(update.error)}</Alert>}
      <div>
        <Button type='submit' variant='primary' size='sm' disabled={update.isPending}>
          저장
        </Button>
      </div>
    </form>
  );
}

export function AgentSettings() {
  const queryClient = useQueryClient();
  const settings = useGetAgentSettings();
  const activity = useGetAgentActivity({ days: 30 });
  const update = useUpdateAgentSettings({
    mutation: { onSuccess: data => queryClient.setQueryData(getGetAgentSettingsQueryKey(), data), onError: notify.error },
  });
  const a = activity.data;

  return (
    <div className='max-w-[760px]'>
      <Section
        title='상담에서 배우기'
        info={
          <p>
            분석이 길었거나 다시 질문한 상담이 끝나면, 다음에 다시 쓸 절차와 기억 후보를 AI에 한 번 더 요청해 제안받습니다. 지금의 공유 범위가 그대로 적용되고, 제안은
            승인하기 전에는 쓰지 않습니다. 답변의 ‘이 상담에서 배우기’ 버튼은 이 설정과 상관없이 쓸 수 있습니다.
          </p>
        }>
        <QueryStatus pending={settings.isPending} error={settings.error} retry={settings.refetch} label='학습 설정' rows={1} />
        {settings.data && (
          <label className='flex items-center gap-3 py-2'>
            <span className='flex-1'>
              <span className='block'>상담이 끝나면 자동으로 배울 점 제안받기</span>
              <span className='block text-xs text-muted-foreground'>켜면 해당 상담마다 AI 호출이 한 번 더 생깁니다.</span>
            </span>
            <Switch
              aria-label='자동 학습 제안'
              checked={settings.data.learning?.enabled ?? false}
              disabled={update.isPending}
              onCheckedChange={value => update.mutate({ data: { learning: { enabled: value }, style: settings.data.style, recording: settings.data.recording } })}
            />
          </label>
        )}
      </Section>

      <Section
        title='상담에서 바로 기록하기'
        info={
          <p>
            ‘오늘 10km 뛰었어’, ‘급여 통장 300만원이야’처럼 말하면 자신의 완료한 운동·현재 계좌 잔액·주식 보유량을 저장합니다. 계획·가정·다른 사람의 실적은 저장하지
            않고, 삭제는 직접 요청해야 합니다. 저장한 기록은 답변에서 바로 되돌릴 수 있습니다.
          </p>
        }>
        {settings.data && (
          <label className='flex items-center gap-3 py-2'>
            <span className='flex-1'>
              <span className='block'>새 상담에서 자동 기록을 켠 상태로 시작</span>
              <span className='block text-xs text-muted-foreground'>입력창의 더보기에서 질문마다 끌 수 있습니다.</span>
            </span>
            <Switch
              aria-label='자동 기록 기본값'
              checked={settings.data.recording?.default_enabled ?? false}
              disabled={update.isPending}
              onCheckedChange={value =>
                update.mutate({ data: { learning: settings.data.learning, style: settings.data.style, recording: { default_enabled: value } } })
              }
            />
          </label>
        )}
      </Section>

      <Section title='상담 방식'>{settings.data && <StyleForm key={JSON.stringify(settings.data.style)} settings={settings.data} />}</Section>

      <Section title='최근 30일'>
        <QueryStatus pending={activity.isPending} error={activity.error} retry={activity.refetch} label='사용 현황' rows={1} />
        {a && (
          <dl className='grid grid-cols-2 gap-3 text-ui md:grid-cols-4'>
            <div>
              <dt className='text-xs text-muted-foreground'>AI 호출</dt>
              <dd className='text-title font-semibold tabular-nums'>{a.model_calls}회</dd>
              {a.failed_calls > 0 && <dd className='text-2xs text-destructive'>완료 못함 {a.failed_calls}회</dd>}
            </div>
            <div>
              <dt className='text-xs text-muted-foreground'>플레이북 사용</dt>
              <dd className='text-title font-semibold tabular-nums'>{a.playbook_uses}번</dd>
            </div>
            <div>
              <dt className='text-xs text-muted-foreground'>배운 절차 제안</dt>
              <dd className='text-title font-semibold tabular-nums'>{a.learning_proposals}건</dd>
              <dd className='text-2xs text-faint'>
                승인 {a.learning_approved} · 거절 {a.learning_rejected}
              </dd>
            </div>
            <div>
              <dt className='text-xs text-muted-foreground'>플레이북</dt>
              <dd>
                <Link href='/reflect/playbooks' className='text-primary hover:underline'>
                  관리하기
                </Link>
              </dd>
            </div>
          </dl>
        )}
      </Section>
    </div>
  );
}
