'use client';

import { useState } from 'react';

import { useMutation } from '@tanstack/react-query';
import { LoaderCircle } from 'lucide-react';

import { errorMessage } from '@/api-client/api-error';
import type { RunView } from '@/api-client/model';
import { Markdown } from '@/components/markdown';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

import { workspaceApi } from '../api';
import { isUnfinished } from '../hooks/use-workspace';

export const RUN_LABEL: Record<RunView['status'], string> = {
  queued: '분석 대기',
  running: '분석 중',
  waiting_input: '답변 필요',
  blocked: '확인 필요',
  cancel_requested: '중지하는 중',
  cancelled: '중지됨',
  completed: '분석 완료',
  failed: '분석 실패',
};

const STAGES: Record<string, string> = {
  summarizing: '이전 대화를 정리하는 중',
  planning: '살펴볼 쟁점을 정리하는 중',
  research_started: '필요한 기록을 찾는 중',
  web_searching: '웹에서 자료를 찾는 중',
  research_finished: '자료 확인 완료',
  analyzing: '대안을 비교하는 중',
  reviewing: '근거와 계산을 검토하는 중',
  answering: '답변을 쓰는 중',
  model_started: '분석하는 중',
  model_finished: '분석 응답 확인 완료',
  structured_output_invalid: '확인된 근거로 답변을 정리하는 중',
};

/**
 * The run as part of the conversation: a status line in the pending answer while it works, the
 * clarifying question when it waits, and the error with a retry when it stops. Nothing once it completes.
 */
export function RunStatus({
  run,
  liveText,
  progress,
  progressMessage,
  reconnecting,
  onRefresh,
  onChoose,
}: {
  run: RunView;
  liveText: string;
  progress: string;
  progressMessage?: string;
  reconnecting: boolean;
  onRefresh: () => Promise<unknown>;
  onChoose: (text: string) => void;
}) {
  const [actionError, setActionError] = useState<string | null>(null);
  const action = useMutation({
    mutationFn: (kind: 'cancel' | 'retry') => workspaceApi[kind](run.id),
    onSuccess: () => {
      setActionError(null);
      return onRefresh();
    },
    onError: e => setActionError(errorMessage(e)),
  });
  if (run.status === 'completed') return null;

  const question = run.clarification;
  const working = isUnfinished(run.status) && run.status !== 'waiting_input' && run.status !== 'blocked';
  const line = reconnecting
    ? '연결을 다시 잇는 중'
    : run.status === 'running'
      ? progressMessage || STAGES[progress] || (run.depth === 'deep' ? '깊게 분석하는 중' : '분석하는 중')
      : RUN_LABEL[run.status];

  return (
    <section className='mx-auto w-full max-w-[760px]' aria-label='답변 진행 상태' aria-live='polite'>
      <div className='rounded-lg border bg-card px-3.5 py-2.5'>
        <div className='flex items-center gap-2 text-ui text-muted-foreground'>
          {working && <LoaderCircle className='size-3.5 animate-spin' aria-hidden />}
          <span className='flex-1'>{line}</span>
          {['queued', 'running', 'waiting_input', 'blocked', 'cancel_requested'].includes(run.status) && (
            <Button size='sm' variant='ghost' disabled={action.isPending || run.status === 'cancel_requested'} onClick={() => action.mutate('cancel')}>
              {run.status === 'cancel_requested' ? '중지 확인 중…' : '중지'}
            </Button>
          )}
          {['failed', 'blocked'].includes(run.status) && (
            <Button size='sm' disabled={action.isPending} onClick={() => action.mutate('retry')}>
              다시 시도
            </Button>
          )}
        </div>
        {liveText && ['running', 'cancel_requested'].includes(run.status) && (
          <div className='typing mt-2'>
            <Markdown text={liveText} />
          </div>
        )}
        {run.status === 'waiting_input' && question && (
          <div className='mt-2 grid gap-2 border-t pt-2'>
            <p className='font-medium'>{question.question}</p>
            {question.reason && <p className='text-ui text-muted-foreground'>{question.reason}</p>}
            <div className='flex flex-wrap gap-2'>
              {question.options?.map(option => (
                <Button key={option} size='sm' onClick={() => onChoose(option)}>
                  {option}
                </Button>
              ))}
              {question.allow_unknown && (
                <Button size='sm' variant='ghost' onClick={() => onChoose('아직 모름')}>
                  아직 모름
                </Button>
              )}
            </div>
          </div>
        )}
        {run.error && (
          <Alert variant='destructive' className='mt-2'>
            {run.error}
          </Alert>
        )}
        {actionError && (
          <Alert variant='destructive' className='mt-2'>
            {actionError}
          </Alert>
        )}
      </div>
    </section>
  );
}
