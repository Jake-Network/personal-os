'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { errorMessage } from '@/api-client/api-error';
import { rateRecommendation, useListRecommendations, getListRecommendationsQueryKey } from '@/api-client/generated/advisor/advisor';
import { useReflectOnAnswer } from '@/api-client/generated/agent/agent';
import { notify } from '@/components/notify';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DecisionFormSheet } from '@/features/memory/components/decision-form';
import { nextRating } from '../utils/answer-actions';

export function AnswerActions({ messageId, conversationId, question }: { messageId: number; conversationId: number; question: string }) {
  const queryClient = useQueryClient();
  const [decision, setDecision] = useState(false);
  const [reason, setReason] = useState<string | null>(null);
  const key = getListRecommendationsQueryKey(conversationId);
  const ratings = useListRecommendations(conversationId);
  const current = ratings.data?.find(item => item.message_id === messageId);
  const feedback = (reason ?? current?.user_feedback ?? '').trim() || null;
  const reasonChanged = feedback !== (current?.user_feedback?.trim() || null);
  const save = useMutation({
    mutationFn: ({ rating, feedback }: { rating: -1 | 1 | null; feedback: string | null; kind: 'rating' | 'reason' }) =>
      rateRecommendation({ message_id: messageId, user_rating: rating, user_feedback: feedback }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  });
  const disabled = save.isPending || !ratings.isSuccess;
  // A stable request ID: asking again returns the same reflection instead of another model call.
  const learn = useReflectOnAnswer({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: ['background-jobs'] });
        notify.success('배울 점을 정리하고 있습니다. 제안은 알림과 승인 대기에서 확인하세요');
      },
      onError: notify.error,
    },
  });
  return (
    <>
      <Button size='sm' variant='ghost' onClick={() => setDecision(true)}>
        결정으로 기록
      </Button>
      <Button
        size='sm'
        variant='ghost'
        title='다음 상담에서 다시 쓸 절차와 기억 후보를 AI에 한 번 더 요청해 제안받습니다. 승인하기 전에는 쓰지 않습니다.'
        disabled={learn.isPending || learn.isSuccess}
        onClick={() => learn.mutate({ messageId, data: { request_id: `reflect:${messageId}` } })}>
        {learn.isSuccess ? '배우는 중' : '이 상담에서 배우기'}
      </Button>
      <Button
        size='icon-sm'
        variant='ghost'
        aria-label='도움이 됐어요'
        aria-pressed={current?.user_rating === 1}
        className='aria-pressed:bg-primary aria-pressed:text-primary-foreground aria-pressed:hover:bg-primary'
        disabled={disabled}
        onClick={() => {
          save.mutate({ rating: nextRating(current?.user_rating, 1), feedback, kind: 'rating' });
        }}>
        <ThumbsUp />
      </Button>
      <Button
        size='icon-sm'
        variant='ghost'
        aria-label='아쉬워요'
        aria-pressed={current?.user_rating === -1}
        className='aria-pressed:bg-primary aria-pressed:text-primary-foreground aria-pressed:hover:bg-primary'
        disabled={disabled}
        onClick={() => {
          save.mutate({ rating: nextRating(current?.user_rating, -1), feedback, kind: 'rating' });
        }}>
        <ThumbsDown />
      </Button>
      {current?.user_rating === -1 && (
        <form
          className='flex w-full gap-1'
          onSubmit={event => {
            event.preventDefault();
            if (!disabled && reasonChanged) save.mutate({ rating: -1, feedback, kind: 'reason' });
          }}>
          <Input
            aria-label='답변이 아쉬운 이유'
            placeholder='아쉬운 점을 한 줄로 남겨 주세요 (선택)'
            value={reason ?? current.user_feedback ?? ''}
            disabled={save.isPending}
            onChange={event => {
              setReason(event.target.value);
              save.reset();
            }}
            maxLength={1000}
          />
          <Button type='submit' size='sm' disabled={disabled || !reasonChanged}>
            {save.isPending && save.variables?.kind === 'reason' ? '저장 중…' : !reasonChanged && feedback ? '저장됨' : '사유 저장'}
          </Button>
        </form>
      )}
      <span role='status' className='text-xs text-faint'>
        {save.isPending && save.variables?.kind === 'rating' ? '평가 저장 중…' :
          save.isSuccess ? (save.variables?.kind === 'reason' ? '사유를 저장했습니다.' : '평가를 저장했습니다.') : ''}
      </span>
      {(save.error || ratings.error) && (
        <Alert variant='destructive'>
          {errorMessage(save.error ?? ratings.error)}
          {ratings.error && <Button onClick={() => void ratings.refetch()}>다시 시도</Button>}
        </Alert>
      )}
      {decision && (
        <DecisionFormSheet
          open
          onClose={() => setDecision(false)}
          defaults={{ title: question }}
          source={{ source_message_id: messageId, conversation_id: conversationId }}
        />
      )}
    </>
  );
}
