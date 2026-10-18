'use client';

import { useState } from 'react';

import { zodResolver } from '@hookform/resolvers/zod';
import { useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useForm } from 'react-hook-form';

import { EmptyState } from '@/components/empty-state';
import { QueryStatus } from '@/components/query-status';
import { notify } from '@/components/notify';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

import { errorMessage } from '@/api-client/api-error';
import { getListDecisionsQueryKey, useCreateDecision, useListDecisions, useReviewDecision } from '@/api-client/generated/memory/memory';
import type { DecisionItem } from '@/api-client/model';
import { dateOnly } from '@/lib/utils/format';

import { type DecisionForm, EMPTY_DECISION, decisionSchema } from '../schema';

export function DecisionJournal() {
  const queryClient = useQueryClient();
  const list = useListDecisions();
  const [open, setOpen] = useState(false);
  const form = useForm<DecisionForm>({ resolver: zodResolver(decisionSchema), defaultValues: EMPTY_DECISION });

  const create = useCreateDecision({
    mutation: {
      onSuccess: () => {
        form.reset(EMPTY_DECISION);
        setOpen(false);
        return queryClient.invalidateQueries({ queryKey: getListDecisionsQueryKey() });
      },
    },
  });

  const submit = form.handleSubmit(f =>
    create.mutate({
      data: {
        title: f.title,
        choice: f.choice,
        rationale: f.rationale,
        alternatives: f.alternatives
          .split('\n')
          .map(s => s.trim())
          .filter(Boolean),
        expected_outcome: f.expected_outcome || null,
        review_on: f.review_on ? new Date(`${f.review_on}T09:00:00`).toISOString() : null,
      },
    }),
  );
  const errors = form.formState.errors;
  const error = Object.values(errors)[0]?.message ?? (create.error ? errorMessage(create.error) : null);

  return (
    <div className='flex flex-col gap-3.5'>
      <div className='flex justify-end'>
        <Button variant='primary' onClick={() => setOpen(v => !v)}>
          결정 기록하기
        </Button>
      </div>
      {open && (
        <Card>
          <form className='flex flex-col gap-2.5 p-4' onSubmit={submit}>
            <Field label='결정 *' id='d-title'>
              <Input id='d-title' placeholder='예: A사 오퍼 수락 여부' {...form.register('title')} />
            </Field>
            <div className='grid grid-cols-1 gap-3.5 md:grid-cols-2'>
              <Field label='선택한 안 *' id='d-choice'>
                <Input id='d-choice' {...form.register('choice')} />
              </Field>
              <Field label='회고 예정일' id='d-review'>
                <Input id='d-review' type='date' {...form.register('review_on')} />
              </Field>
            </div>
            <Field label='고려한 대안 (줄마다 하나)' id='d-alt'>
              <Textarea id='d-alt' {...form.register('alternatives')} />
            </Field>
            <Field label='선택 이유 *' id='d-why'>
              <Textarea id='d-why' {...form.register('rationale')} />
            </Field>
            <Field label='예상 결과' id='d-expected'>
              <Textarea id='d-expected' {...form.register('expected_outcome')} />
            </Field>
            {error && <Alert variant='destructive'>{error}</Alert>}
            <div className='flex justify-end gap-2'>
              <Button type='button' onClick={() => setOpen(false)}>
                취소
              </Button>
              <Button type='submit' variant='primary' disabled={create.isPending}>
                기록
              </Button>
            </div>
          </form>
        </Card>
      )}
      <QueryStatus pending={list.isPending} error={list.error} retry={list.refetch} label='의사결정 기록' />
      {!list.error && list.data?.length === 0 && (
        <Card>
          <EmptyState>기록된 의사결정이 없습니다.</EmptyState>
        </Card>
      )}
      {list.data?.map(d => (
        <DecisionCard key={d.id} decision={d} />
      ))}
    </div>
  );
}

function Field({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div className='flex flex-col gap-1'>
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}

function DecisionCard({ decision: d }: { decision: DecisionItem }) {
  const queryClient = useQueryClient();
  const [reviewing, setReviewing] = useState(false);
  const [outcome, setOutcome] = useState('');
  const review = useReviewDecision({
    mutation: {
      onSuccess: () => {
        setReviewing(false);
        return queryClient.invalidateQueries({ queryKey: getListDecisionsQueryKey() });
      },
      onError: notify.error,
    },
  });
  // Rendered on the client only (the page is a client tree fetched after mount), so `new Date()` is stable enough.
  const reviewDue = !d.reviewed_at && d.review_on && new Date(d.review_on) < new Date();

  return (
    <Card className='flex flex-col gap-1.5 p-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <h2 className='flex-1 text-[15px]'>{d.title}</h2>
        <span className='text-xs text-faint'>{dateOnly(d.decided_at)}</span>
        {d.reviewed_at ? <Badge variant='success'>회고 완료</Badge> : reviewDue ? <Badge variant='warning'>회고 시점 지남</Badge> : null}
      </div>
      <div>
        <span className='text-muted-foreground'>선택:</span> {d.choice}
      </div>
      {d.alternatives.length > 0 && (
        <div className='text-xs'>
          <span className='text-muted-foreground'>대안:</span> {d.alternatives.join(' · ')}
        </div>
      )}
      <div className='text-xs'>
        <span className='text-muted-foreground'>이유:</span> {d.rationale}
      </div>
      <div className='mt-1.5 grid grid-cols-1 gap-3.5 md:grid-cols-2'>
        <div className='rounded-md bg-muted p-4'>
          <div className='text-xs text-faint'>예상 결과</div>
          {d.expected_outcome ?? '—'}
        </div>
        <div className='rounded-md bg-muted p-4'>
          <div className='text-xs text-faint'>실제 결과</div>
          {d.actual_outcome ??
            (reviewing ? (
              <div className='mt-1 flex flex-col gap-2.5'>
                <Textarea value={outcome} onChange={e => setOutcome(e.target.value)} />
                <div className='flex gap-2'>
                  <Button
                    size='sm'
                    variant='primary'
                    disabled={!outcome.trim() || review.isPending}
                    onClick={() => review.mutate({ entryId: d.id, data: { actual_outcome: outcome } })}>
                    저장
                  </Button>
                  <Button size='sm' onClick={() => setReviewing(false)}>
                    취소
                  </Button>
                </div>
              </div>
            ) : (
              <Button size='sm' className='mt-1' onClick={() => setReviewing(true)}>
                결과 기록
              </Button>
            ))}
        </div>
      </div>
      {d.conversation_id && (
        <Link href={`/advisor/${d.conversation_id}`} className='text-xs text-primary hover:underline'>
          관련 상담 보기
        </Link>
      )}
    </Card>
  );
}
