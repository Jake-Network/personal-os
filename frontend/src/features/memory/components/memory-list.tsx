'use client';

import { useState } from 'react';
import { MemoryRevisions } from './memory-revisions';

import { zodResolver } from '@hookform/resolvers/zod';
import { useQueryClient } from '@tanstack/react-query';
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
import { NativeSelect } from '@/components/ui/native-select';

import { errorMessage } from '@/api-client/api-error';
import { getListMemoriesQueryKey, useCreateMemory, useDeleteMemory, useListMemories } from '@/api-client/generated/memory/memory';
import { MEMORY_KIND_LABEL } from '@/lib/labels';

import { type MemoryForm, memorySchema } from '../schema';

export function MemoryList() {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState<number | null>(null);
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

  const fieldError = form.formState.errors.content?.message;
  const error = fieldError ?? (create.error ? errorMessage(create.error) : null);

  return (
    <div className='flex flex-col gap-3.5'>
      <Card>
        <form className='flex flex-wrap items-end gap-2 p-4' onSubmit={form.handleSubmit(data => create.mutate({ data }))}>
          <div className='flex w-[130px] flex-none flex-col gap-1'>
            <Label htmlFor='m-kind'>종류</Label>
            <NativeSelect id='m-kind' {...form.register('kind')}>
              {Object.entries(MEMORY_KIND_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className='flex min-w-40 flex-1 flex-col gap-1'>
            <Label htmlFor='m-content'>내용</Label>
            <Input id='m-content' placeholder='예: 연봉보다 성장 기회를 우선한다' {...form.register('content')} />
          </div>
          <Button variant='primary' type='submit' disabled={create.isPending}>
            저장
          </Button>
        </form>
      </Card>
      {error && <Alert variant='destructive'>{error}</Alert>}
      <Card>
        <QueryStatus pending={list.isPending} error={list.error} retry={list.refetch} label='저장된 기억' />
        <ul>
          {list.data?.map(m => (
            <li key={m.id} className='border-b px-4 py-2 last:border-0'>
              <div className='flex flex-wrap items-baseline gap-2.5'>
                <Badge variant='accent'>{MEMORY_KIND_LABEL[m.kind]}</Badge>
                <span className='flex-1'>{m.content}</span>
                <span className='text-xs text-faint'>{m.source === 'advisor' ? 'AI 제안 → 확인' : '직접 입력'}</span>
                <Button size='sm' onClick={() => setExpanded(expanded === m.id ? null : m.id)}>
                  수정 · 이력
                </Button>
                <Button size='sm' variant='ghost-destructive' onClick={() => confirm('이 기억을 삭제할까요?') && remove.mutate({ memoryId: m.id })}>
                  삭제
                </Button>
              </div>
              {expanded === m.id && <MemoryRevisions memory={m} />}
            </li>
          ))}
        </ul>
        {!list.error && list.data?.length === 0 && <EmptyState>저장된 기억이 없습니다.</EmptyState>}
      </Card>
    </div>
  );
}
