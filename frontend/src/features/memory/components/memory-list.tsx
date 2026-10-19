'use client';

import { useState } from 'react';

import { zodResolver } from '@hookform/resolvers/zod';
import { useQueryClient } from '@tanstack/react-query';
import { Brain, Check, Trash2, X } from 'lucide-react';
import { useForm } from 'react-hook-form';

import { errorMessage } from '@/api-client/api-error';
import {
  getListMemoriesQueryKey,
  useConfirmMemory,
  useCreateMemory,
  useDeleteMemory,
  useListMemories,
  useRejectMemory,
} from '@/api-client/generated/memory/memory';
import type { MemoryItem } from '@/api-client/model';
import { useConfirm } from '@/components/confirm-dialog';
import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { MEMORY_KIND_LABEL } from '@/lib/labels';
import { dateOnly } from '@/lib/utils/format';

import { type MemoryForm, memorySchema } from '../schema';
import { MemoryRevisions } from './memory-revisions';

function Proposed({ memory: m }: { memory: MemoryItem }) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: getListMemoriesQueryKey() });
  const accept = useConfirmMemory({ mutation: { onSuccess: invalidate, onError: notify.error } });
  const reject = useRejectMemory({ mutation: { onSuccess: invalidate, onError: notify.error } });
  const busy = accept.isPending || reject.isPending;
  return (
    <li className='flex flex-wrap items-center gap-2 py-2.5'>
      <Badge variant='warning'>{MEMORY_KIND_LABEL[m.kind] ?? m.kind}</Badge>
      <span className='min-w-0 flex-1'>{m.content}</span>
      <span className='text-xs text-faint'>{dateOnly(m.created_at)} 상담에서 제안</span>
      <Button size='sm' variant='primary' disabled={busy} onClick={() => accept.mutate({ memoryId: m.id })}>
        <Check /> 맞아요, 저장
      </Button>
      <Button size='sm' variant='ghost' disabled={busy} onClick={() => reject.mutate({ memoryId: m.id })}>
        <X /> 아니에요
      </Button>
    </li>
  );
}

export function MemoryList() {
  const queryClient = useQueryClient();
  const confirmDialog = useConfirm();
  const [expanded, setExpanded] = useState<number | null>(null);
  const proposed = useListMemories({ status: 'proposed' });
  const list = useListMemories({ status: 'confirmed' });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: getListMemoriesQueryKey() });
  const form = useForm<MemoryForm>({ resolver: zodResolver(memorySchema), defaultValues: { kind: 'preference', content: '' } });

  const create = useCreateMemory({
    mutation: {
      onSuccess: () => {
        form.reset({ kind: form.getValues('kind'), content: '' });
        return invalidate();
      },
    },
  });
  const remove = useDeleteMemory({ mutation: { onSuccess: invalidate, onError: notify.error } });
  const askRemove = async (m: MemoryItem) => {
    const ok = await confirmDialog({
      title: '이 기억을 삭제할까요?',
      description: '이후 상담에서 더는 사용하지 않습니다. 이미 받은 답변의 텍스트는 대화에 그대로 남습니다.',
      confirmLabel: '삭제',
      destructive: true,
    });
    if (ok) remove.mutate({ memoryId: m.id });
  };

  const fieldError = form.formState.errors.content?.message;
  const error = fieldError ?? (create.error ? errorMessage(create.error) : null);

  return (
    <>
      {(proposed.error || (proposed.data?.length ?? 0) > 0) && (
        <Section title='확인 필요' count={proposed.data?.length} info={<p>상담 중에 AI가 알아낸 내용입니다. 저장하기 전에는 상담에 사실로 쓰지 않습니다.</p>}>
          <QueryStatus pending={false} error={proposed.error} retry={proposed.refetch} label='확인할 기억' />
          <ul className='divide-y'>
            {proposed.data?.map(m => (
              <Proposed key={m.id} memory={m} />
            ))}
          </ul>
        </Section>
      )}

      <Section title='저장된 기억' count={list.data?.length} info={<p>확인된 기억만 상담에서 나의 선호·제약·우선순위로 사용합니다. 공유 설정에서 개인 프로필을 끄면 전송하지 않습니다.</p>}>
        <form className='flex flex-wrap items-end gap-2 py-2' onSubmit={form.handleSubmit(data => create.mutate({ data }))}>
          <div className='flex w-28 flex-none flex-col gap-1'>
            <Label htmlFor='m-kind'>종류</Label>
            <NativeSelect id='m-kind' {...form.register('kind')}>
              {Object.entries(MEMORY_KIND_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className='flex min-w-48 flex-1 flex-col gap-1'>
            <Label htmlFor='m-content'>내용</Label>
            <Input id='m-content' placeholder='예: 연봉보다 성장 기회를 우선한다' {...form.register('content')} />
          </div>
          <Button variant='primary' type='submit' disabled={create.isPending}>
            추가
          </Button>
        </form>
        {error && <Alert variant='destructive'>{error}</Alert>}
        <QueryStatus pending={list.isPending} error={list.error} retry={list.refetch} label='저장된 기억' />
        {list.data?.length === 0 && (
          <EmptyState icon={Brain} title='저장된 기억이 없습니다'>
            지켜야 할 조건이나 우선순위를 적어 두면 상담이 그 기준으로 답합니다.
          </EmptyState>
        )}
        <ul className='divide-y'>
          {list.data?.map(m => (
            <li key={m.id} className='py-2'>
              <div className='flex flex-wrap items-center gap-2'>
                <Badge variant='accent'>{MEMORY_KIND_LABEL[m.kind] ?? m.kind}</Badge>
                <span className='min-w-0 flex-1'>{m.content}</span>
                <span className='text-xs text-faint'>{m.source === 'advisor' ? '상담에서 확인' : '직접 입력'}</span>
                <Button size='sm' variant='ghost' aria-expanded={expanded === m.id} onClick={() => setExpanded(expanded === m.id ? null : m.id)}>
                  {expanded === m.id ? '닫기' : '고치기'}
                </Button>
                <Button size='icon-sm' variant='ghost-destructive' aria-label='삭제' onClick={() => void askRemove(m)}>
                  <Trash2 />
                </Button>
              </div>
              {expanded === m.id && <MemoryRevisions memory={m} />}
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}
