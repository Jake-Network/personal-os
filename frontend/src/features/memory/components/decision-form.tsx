'use client';
import { zodResolver } from '@hookform/resolvers/zod';
import { useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { errorMessage } from '@/api-client/api-error';
import { getListDecisionsQueryKey, useCreateDecision } from '@/api-client/generated/memory/memory';
import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';
import type { DecisionCreate } from '@/api-client/model';
import { notify } from '@/components/notify';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import { zonedInstant } from '@/lib/utils/zoned';
import { type DecisionForm, EMPTY_DECISION, decisionSchema, decisionDefaults } from '../schema';
function Field({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div className='flex flex-col gap-1'>
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}

export function DecisionFormSheet({
  open,
  onClose,
  defaults = {},
  source = {},
}: {
  open: boolean;
  onClose: () => void;
  defaults?: Partial<DecisionForm>;
  source?: Partial<Pick<DecisionCreate, 'conversation_id' | 'context_snapshot_id' | 'source_message_id'>>;
}) {
  const queryClient = useQueryClient();
  const form = useForm<DecisionForm>({ resolver: zodResolver(decisionSchema), defaultValues: decisionDefaults(defaults) });
  const create = useCreateDecision({
    mutation: {
      onSuccess: async () => {
        form.reset(EMPTY_DECISION);
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: getListDecisionsQueryKey() }),
          queryClient.invalidateQueries({ queryKey: getSummaryQueryKey() }),
        ]);
        notify.success('결정을 기록했습니다');
        onClose();
      },
    },
  });
  const submit = form.handleSubmit(f =>
    create.mutate({
      data: {
        ...source,
        title: f.title,
        choice: f.choice,
        rationale: f.rationale,
        alternatives: f.alternatives
          .split('\n')
          .map(s => s.trim())
          .filter(Boolean),
        expected_outcome: f.expected_outcome || null,
        // 09:00 on the chosen day in the app's timezone.
        review_on: f.review_on ? zonedInstant(f.review_on, 9 * 60) : null,
      },
    }),
  );
  const error = Object.values(form.formState.errors)[0]?.message ?? (create.error ? errorMessage(create.error) : null);

  return (
    <Sheet open={open} onOpenChange={o => !o && onClose()}>
      <SheetContent side='right' className='w-[min(520px,100vw)] overflow-y-auto'>
        <form className='flex flex-col gap-3 p-5' onSubmit={submit}>
          <SheetTitle className='pr-8 text-title font-semibold'>결정 기록하기</SheetTitle>
          <Field label='결정 *' id='d-title'>
            <Input id='d-title' placeholder='예: A사 오퍼 수락 여부' {...form.register('title')} />
          </Field>
          <Field label='선택한 안 *' id='d-choice'>
            <Input id='d-choice' {...form.register('choice')} />
          </Field>
          <Field label='고려한 대안 (줄마다 하나)' id='d-alt'>
            <Textarea id='d-alt' {...form.register('alternatives')} />
          </Field>
          <Field label='선택 이유 *' id='d-why'>
            <Textarea id='d-why' {...form.register('rationale')} />
          </Field>
          <Field label='예상 결과' id='d-expected'>
            <Textarea id='d-expected' placeholder='나중에 실제 결과와 비교합니다' {...form.register('expected_outcome')} />
          </Field>
          <Field label='회고할 날' id='d-review'>
            <Input id='d-review' type='date' {...form.register('review_on')} />
          </Field>
          {error && <Alert variant='destructive'>{error}</Alert>}
          <div className='flex justify-end gap-2'>
            <Button type='button' onClick={onClose}>
              취소
            </Button>
            <Button type='submit' variant='primary' disabled={create.isPending}>
              기록
            </Button>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}
