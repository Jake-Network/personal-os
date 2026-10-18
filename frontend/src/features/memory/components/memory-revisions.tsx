'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import type { MemoryItem, MemoryRevisionItem } from '@/api-client/model';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { notify } from '@/components/notify';
import { QueryStatus } from '@/components/query-status';
import { dateTime } from '@/lib/utils/format';

export function MemoryRevisions({ memory }: { memory: MemoryItem }) {
  const client = useQueryClient();
  const path = `/api/memories/${memory.id}/revisions`;
  const revisions = useQuery({ queryKey: [path], queryFn: () => customInstance<MemoryRevisionItem[]>({ url: path }) });
  const [content, setContent] = useState(memory.content);
  const [scope, setScope] = useState('');
  const [from, setFrom] = useState('');
  const [until, setUntil] = useState('');
  const [external, setExternal] = useState(false);
  const latest = revisions.data?.at(-1);
  const save = useMutation({
    mutationFn: () =>
      customInstance({
        url: path,
        method: 'POST',
        data: {
          kind: memory.kind,
          content,
          scope: scope || null,
          valid_from: from ? new Date(from).toISOString() : null,
          valid_until: until ? new Date(until).toISOString() : null,
          expected_revision: latest?.revision ?? 0,
          external_allowed: external,
          source_references: latest?.source_references ?? [],
        },
      }),
    onSuccess: () => Promise.all([client.invalidateQueries({ queryKey: [path] }), client.invalidateQueries({ queryKey: ['/api/memories'] })]),
    onError: notify.error,
  });
  return (
    <div className='space-y-3 border-t p-4'>
      <p>수정본은 이전 기록을 보존하며 누적됩니다.</p>
      <label className='block'>
        새 내용
        <Input value={content} onChange={e => setContent(e.target.value)} />
      </label>
      <label className='block'>
        적용 범위 (회사·프로젝트 등)
        <Input value={scope} onChange={e => setScope(e.target.value)} />
      </label>
      <div className='flex flex-wrap gap-3'>
        <label>
          유효 시작 (이 기기의 시간)
          <Input type='datetime-local' value={from} onChange={e => setFrom(e.target.value)} />
        </label>
        <label>
          유효 종료 (이 기기의 시간)
          <Input type='datetime-local' value={until} onChange={e => setUntil(e.target.value)} />
        </label>
      </div>
      <label className='flex gap-2'>
        <input type='checkbox' checked={external} onChange={e => setExternal(e.target.checked)} />
        외부 상담 전송 허용 (끄면 과거 파생 근거도 전송에서 제외)
      </label>
      <Button disabled={save.isPending || revisions.isPending || !!revisions.error || !content.trim()} onClick={() => save.mutate()}>
        수정본 확인 · 저장
      </Button>
      <QueryStatus pending={revisions.isPending} error={revisions.error} retry={revisions.refetch} label='기억 수정 이력' />
      <ol>
        {revisions.data?.map(r => (
          <li key={r.id} className='border-t py-2 text-sm'>
            v{r.revision} · {dateTime(r.created_at)} · {r.external_allowed ? '외부 전송 허용' : '로컬 전용'}
            <p>{r.content}</p>
            <p className='text-faint'>
              {r.valid_from ? dateTime(r.valid_from) : '시작 미지정'} ~ {r.valid_until ? dateTime(r.valid_until) : '종료 미지정'}
            </p>
          </li>
        ))}
      </ol>
    </div>
  );
}
