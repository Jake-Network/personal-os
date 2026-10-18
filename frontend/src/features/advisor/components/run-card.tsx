'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import type { RunView } from '@/api-client/model';
import { errorMessage } from '@/api-client/api-error';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Markdown } from '@/components/markdown';
import { workspaceApi } from '../api';
import type { MemoryProposal } from '../types';
import { MemoryProposalCard } from './proposal-card';

export const RUN_LABEL: Record<RunView['status'], string> = {
  queued: '분석 대기',
  running: '분석 중',
  waiting_input: '답변 필요',
  blocked: '확인 필요',
  cancel_requested: '중지 요청 중',
  cancelled: '중지됨',
  completed: '분석 완료',
  failed: '분석 실패',
};

const STAGES: Record<string, string> = {
  summarizing: '이전 대화의 근거와 요약을 정리하는 중',
  planning: '조사할 쟁점을 정리하는 중',
  research_started: '필요한 근거를 조회하는 중',
  research_finished: '근거 조회 완료',
  analyzing: '대안별 조건과 결과를 비교하는 중',
  reviewing: '근거와 계산을 검토하는 중',
  answering: '최종 답변을 작성하는 중',
  model_started: '분석 요청을 처리하는 중',
  model_finished: '분석 응답 확인 완료',
};

export function RunCard({
  run,
  liveText,
  progress,
  reconnecting,
  onRefresh,
  onChoose,
}: {
  run: RunView;
  liveText: string;
  progress: string;
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
  const question = run.clarification;
  const memories = (Array.isArray(run.result?.memory_proposals) ? run.result.memory_proposals : []) as MemoryProposal[];
  const limitations = (Array.isArray(run.result?.limitations) ? run.result.limitations : []) as string[];
  return (
    <section className='mx-auto grid w-full max-w-[760px] gap-2 rounded-lg border bg-card p-3' aria-label='상담 실행' aria-live='polite'>
      <div className='flex flex-wrap items-center gap-2'>
        <Badge variant={run.status === 'waiting_input' ? 'warning' : run.status === 'completed' ? 'success' : 'default'}>
          {RUN_LABEL[run.status]}
        </Badge>
        <span className='text-xs text-faint'>
          {run.depth === 'deep' ? '깊게 분석' : '자동 분석'} · 답변 버전 {run.answer_revision}
        </span>
        {reconnecting && <span className='text-xs text-faint'>연결 복구 중 · 저장된 상태 확인 중</span>}
      </div>
      {['queued', 'running'].includes(run.status) && <p className='text-xs text-faint'>다른 화면으로 이동해도 서버에서 분석을 계속합니다.</p>}
      {run.status === 'running' && STAGES[progress] && <p className='text-sm'>{STAGES[progress]}</p>}
      {run.status === 'waiting_input' && question && (
        <>
          <h3 className='font-medium'>{question.question}</h3>
          {question.reason && <p className='text-sm text-muted-foreground'>{question.reason}</p>}
          <div className='flex flex-wrap gap-2'>
            {question.options?.map(option => (
              <Button key={option} size='sm' onClick={() => onChoose(option)}>
                {option}
              </Button>
            ))}
            {question.allow_unknown && (
              <Button size='sm' onClick={() => onChoose('아직 모름')}>
                아직 모름
              </Button>
            )}
          </div>
          <p className='text-xs text-faint'>아래 입력창에 직접 답할 수도 있습니다.</p>
        </>
      )}
      {liveText && ['running', 'cancel_requested'].includes(run.status) && <Markdown text={liveText} />}
      {run.error && <Alert variant='destructive'>{run.error}</Alert>}
      {limitations.length > 0 && (
        <div className='text-xs text-warning'>
          <p>분석 범위와 남은 불확실성</p>
          <ul className='list-disc pl-4'>
            {limitations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {memories.map(memory => (
        <MemoryProposalCard key={memory.id} memory={memory} />
      ))}
      {actionError && <Alert variant='destructive'>{actionError}</Alert>}
      <div className='flex gap-2'>
        {['queued', 'running', 'waiting_input', 'blocked', 'cancel_requested'].includes(run.status) && (
          <Button size='sm' disabled={action.isPending || run.status === 'cancel_requested'} onClick={() => action.mutate('cancel')}>
            {run.status === 'cancel_requested' ? '중지 확인 중…' : '분석 중지'}
          </Button>
        )}
        {['failed', 'blocked'].includes(run.status) && (
          <Button size='sm' disabled={action.isPending} onClick={() => action.mutate('retry')}>
            분석 재시도
          </Button>
        )}
      </div>
    </section>
  );
}
