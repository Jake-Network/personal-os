'use client';

import { useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MessagesSquare, Plus, Scale } from 'lucide-react';
import Link from 'next/link';

import { customInstance } from '@/api-client/custom-client';
import { getListDecisionsQueryKey, useListDecisions, useReviewDecision } from '@/api-client/generated/memory/memory';
import type { DecisionItem } from '@/api-client/model';
import { TabToolbar } from '@/components/area-layout';
import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { QueryStatus } from '@/components/query-status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import { dateOnly } from '@/lib/utils/format';

import { useRecordParam } from '@/features/personal-data/hooks/use-record-param';

import { DecisionFormSheet } from './decision-form';
import { isDecisionReviewDue } from '../review-due';
import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';

interface Outcome {
  id: number;
  actual_outcome: string;
  lessons: string | null;
  next_action: string | null;
  expected_outcome: string | null;
  reviewed_at: string | null;
}

function reviewState(d: DecisionItem, now: number) {
  if (d.reviewed_at) return <Badge variant='success'>회고 완료</Badge>;
  if (isDecisionReviewDue(d, now)) return <Badge variant='warning'>회고할 때</Badge>;
  if (d.review_on) return <span className='text-xs text-faint'>회고 {dateOnly(d.review_on)}</span>;
  return null;
}

/** The decision's first recorded outcome (on the decision itself) and later outcome reviews are kept apart. */
function DecisionDetail({ decision: d, onClose }: { decision: DecisionItem; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [actual, setActual] = useState('');
  const [more, setMore] = useState('');
  const review = useReviewDecision({
    mutation: {
      onSuccess: () => {
        setActual('');
        return Promise.all([
          queryClient.invalidateQueries({ queryKey: getListDecisionsQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getSummaryQueryKey() }),
        ]);
      },
      onError: notify.error,
    },
  });
  const outcomesKey = ['decision-outcomes', d.id];
  const outcomes = useQuery({ queryKey: outcomesKey, queryFn: () => customInstance<Outcome[]>({ url: `/api/decisions/${d.id}/reviews` }) });
  const addOutcome = useMutation({
    mutationFn: () => customInstance({ method: 'POST', url: `/api/decisions/${d.id}/reviews`, data: { actual_outcome: more } }),
    onSuccess: () => {
      setMore('');
      return queryClient.invalidateQueries({ queryKey: outcomesKey });
    },
    onError: notify.error,
  });

  return (
    <Sheet open onOpenChange={o => !o && onClose()}>
      <SheetContent side='right' className='w-[min(560px,100vw)] overflow-y-auto'>
        <div className='flex flex-col gap-4 p-5'>
          <div>
            <SheetTitle className='pr-8 text-title font-semibold'>{d.title}</SheetTitle>
            <p className='mt-1 text-xs text-muted-foreground'>{dateOnly(d.decided_at)}에 결정</p>
          </div>
          <dl className='grid gap-2 text-ui'>
            <div>
              <dt className='text-xs text-faint'>선택</dt>
              <dd>{d.choice}</dd>
            </div>
            {d.alternatives.length > 0 && (
              <div>
                <dt className='text-xs text-faint'>대안</dt>
                <dd>{d.alternatives.join(' · ')}</dd>
              </div>
            )}
            <div>
              <dt className='text-xs text-faint'>이유</dt>
              <dd className='whitespace-pre-wrap'>{d.rationale}</dd>
            </div>
          </dl>
          {d.conversation_id && (
            <Link href={`/advisor/${d.conversation_id}`} className='inline-flex items-center gap-1.5 text-ui text-primary hover:underline'>
              <MessagesSquare className='size-3.5' aria-hidden /> 결정한 상담 열기
            </Link>
          )}
          <div className='grid grid-cols-1 gap-3 md:grid-cols-2'>
            <div className='rounded-md bg-muted p-3'>
              <div className='mb-1 text-xs text-faint'>예상했던 결과</div>
              <p className='whitespace-pre-wrap'>{d.expected_outcome ?? '기록하지 않음'}</p>
            </div>
            <div className='rounded-md bg-muted p-3'>
              <div className='mb-1 text-xs text-faint'>실제 결과</div>
              {d.actual_outcome ? (
                <p className='whitespace-pre-wrap'>{d.actual_outcome}</p>
              ) : (
                <div className='flex flex-col gap-2'>
                  <Textarea aria-label='실제 결과' value={actual} onChange={e => setActual(e.target.value)} />
                  <Button
                    size='sm'
                    variant='primary'
                    className='self-start'
                    disabled={!actual.trim() || review.isPending}
                    onClick={() => review.mutate({ entryId: d.id, data: { actual_outcome: actual } })}>
                    저장
                  </Button>
                </div>
              )}
            </div>
          </div>

          <section className='flex flex-col gap-2'>
            <h3 className='border-b pb-1 text-ui font-semibold'>이후 결과 회고</h3>
            <QueryStatus pending={outcomes.isPending} error={outcomes.error} retry={outcomes.refetch} label='결과 회고' rows={2} />
            {outcomes.data?.length === 0 && <p className='text-xs text-faint'>시간이 지나 다시 돌아본 결과를 쌓아 두세요.</p>}
            <ul className='flex flex-col gap-2'>
              {outcomes.data?.map(o => (
                <li key={o.id} className='border-l-2 pl-3 text-ui'>
                  <div className='text-xs text-faint'>{o.reviewed_at ? dateOnly(o.reviewed_at) : '날짜 미기록'}</div>
                  <p className='whitespace-pre-wrap'>{o.actual_outcome}</p>
                  {o.lessons && <p className='text-xs text-muted-foreground'>배운 점: {o.lessons}</p>}
                  {o.next_action && <p className='text-xs text-muted-foreground'>다음 행동: {o.next_action}</p>}
                </li>
              ))}
            </ul>
            <Textarea aria-label='새 결과 회고' placeholder='지금 돌아보면 어떻게 됐나요?' value={more} onChange={e => setMore(e.target.value)} />
            <Button size='sm' className='self-start' disabled={!more.trim() || addOutcome.isPending} onClick={() => addOutcome.mutate()}>
              결과 회고 추가
            </Button>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}

/** Decisions with what was expected, so they can be compared with what happened. */
export function DecisionJournal({ recordId }: { recordId: number | null }) {
  const list = useListDecisions();
  const [selected, setSelected] = useRecordParam(recordId);
  const [creating, setCreating] = useState(false);
  const [now] = useState(() => Date.now());
  const open = selected !== null ? list.data?.find(d => d.id === selected) : undefined;

  return (
    <div className='max-w-[860px]'>
      <TabToolbar>
        <Button variant='primary' onClick={() => setCreating(true)}>
          <Plus /> 결정 기록하기
        </Button>
      </TabToolbar>
      <QueryStatus pending={list.isPending} error={list.error} retry={list.refetch} label='결정 기록' />
      {list.data?.length === 0 && (
        <EmptyState
          icon={Scale}
          title='기록된 결정이 없습니다'
          action={
            <Button variant='primary' onClick={() => setCreating(true)}>
              <Plus /> 결정 기록하기
            </Button>
          }>
          선택과 이유, 예상한 결과를 남겨 두면 나중에 실제 결과와 비교할 수 있습니다.
        </EmptyState>
      )}
      <ul className='divide-y'>
        {list.data?.map(d => (
          <li key={d.id}>
            <button type='button' onClick={() => setSelected(d.id)} className='flex w-full flex-col gap-0.5 py-3 text-left hover:bg-muted/40'>
              <span className='flex flex-wrap items-center gap-2'>
                <span className='font-medium'>{d.title}</span>
                {reviewState(d, now)}
                <span className='ml-auto text-xs tabular-nums text-faint'>{dateOnly(d.decided_at)}</span>
              </span>
              <span className='text-ui text-muted-foreground'>선택: {d.choice}</span>
            </button>
          </li>
        ))}
      </ul>
      {creating && <DecisionFormSheet open onClose={() => setCreating(false)} />}
      {open && <DecisionDetail key={open.id} decision={open} onClose={() => setSelected(null)} />}
    </div>
  );
}
