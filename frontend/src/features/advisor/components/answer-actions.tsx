'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { errorMessage } from '@/api-client/api-error';
import { rateRecommendation, useListRecommendations, getListRecommendationsQueryKey } from '@/api-client/generated/advisor/advisor';
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
  const save = useMutation({
    mutationFn: ({ rating, feedback = null }: { rating: -1 | 1 | null; feedback?: string | null }) =>
      rateRecommendation({ message_id: messageId, user_rating: rating, user_feedback: feedback }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  });
  const disabled = save.isPending || !ratings.isSuccess;
  return (
    <>
      <Button size='sm' variant='ghost' onClick={() => setDecision(true)}>
        결정으로 기록
      </Button>
      <Button
        size='icon-sm'
        variant='ghost'
        aria-label='도움이 됐어요'
        aria-pressed={current?.user_rating === 1}
        disabled={disabled}
        onClick={() => {
          setReason(null);
          save.mutate({ rating: nextRating(current?.user_rating, 1) });
        }}>
        <ThumbsUp />
      </Button>
      <Button
        size='icon-sm'
        variant='ghost'
        aria-label='아쉬워요'
        aria-pressed={current?.user_rating === -1}
        disabled={disabled}
        onClick={() => {
          setReason(null);
          save.mutate({ rating: nextRating(current?.user_rating, -1) });
        }}>
        <ThumbsDown />
      </Button>
      {current?.user_rating === -1 && (
        <form
          className='flex w-full gap-1'
          onSubmit={event => {
            event.preventDefault();
            save.mutate({ rating: -1, feedback: (reason ?? current.user_feedback ?? '').trim() || null });
          }}>
          <Input
            aria-label='답변이 아쉬운 이유'
            placeholder='아쉬운 점을 한 줄로 남겨 주세요 (선택)'
            value={reason ?? current.user_feedback ?? ''}
            onChange={event => setReason(event.target.value)}
            maxLength={1000}
          />
          <Button type='submit' size='sm' disabled={disabled}>
            사유 저장
          </Button>
        </form>
      )}
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
