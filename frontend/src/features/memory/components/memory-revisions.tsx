'use client';

import { useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { customInstance } from '@/api-client/custom-client';
import type { MemoryItem, MemoryRevisionItem } from '@/api-client/model';
import { notify } from '@/components/notify';
import { QueryStatus } from '@/components/query-status';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { dateOnly, dateTime } from '@/lib/utils/format';
import { addDays, zonedDayKey, zonedMidnight, zonedMinutes } from '@/lib/utils/zoned';

/** A new version of a memory; earlier versions stay in the record. */
export function MemoryRevisions({ memory }: { memory: MemoryItem }) {
  const client = useQueryClient();
  const path = `/api/memories/${memory.id}/revisions`;
  const revisions = useQuery({ queryKey: [path], queryFn: () => customInstance<MemoryRevisionItem[]>({ url: path }) });
  const latest = revisions.data?.at(-1);
  const [content, setContent] = useState(memory.content);
  const [scope, setScope] = useState('');
  const [from, setFrom] = useState('');
  const [until, setUntil] = useState('');
  const [external, setExternal] = useState(false);
  const save = useMutation({
    mutationFn: () =>
      customInstance({
        url: path,
        method: 'POST',
        data: {
          kind: memory.kind,
          content,
          scope: scope || null,
          // Validity is by day in the app's timezone; "until" includes the whole last day.
          valid_from: from ? zonedMidnight(from) : null,
          valid_until: until ? zonedMidnight(addDays(until, 1)) : null,
          expected_revision: latest?.revision ?? 0,
          external_allowed: external,
          source_references: latest?.source_references ?? [],
        },
      }),
    onSuccess: async () => {
      await Promise.all([client.invalidateQueries({ queryKey: [path] }), client.invalidateQueries({ queryKey: ['/api/memories'] })]);
      notify.success('수정본을 저장했습니다');
    },
    onError: notify.error,
  });
  const id = `rev-${memory.id}`;
  return (
    <div className='mt-2 flex flex-col gap-3 rounded-lg border bg-muted/30 p-3'>
      <div className='flex flex-col gap-1'>
        <Label htmlFor={`${id}-content`}>내용</Label>
        <Input id={`${id}-content`} value={content} onChange={e => setContent(e.target.value)} />
      </div>
      <div className='flex flex-col gap-1'>
        <Label htmlFor={`${id}-scope`}>적용 범위 (회사·프로젝트 등, 선택)</Label>
        <Input id={`${id}-scope`} value={scope} onChange={e => setScope(e.target.value)} />
      </div>
      <div className='flex flex-wrap gap-3'>
        <div className='flex flex-col gap-1'>
          <Label htmlFor={`${id}-from`}>언제부터</Label>
          <Input id={`${id}-from`} type='date' value={from} onChange={e => setFrom(e.target.value)} />
        </div>
        <div className='flex flex-col gap-1'>
          <Label htmlFor={`${id}-until`}>언제까지</Label>
          <Input id={`${id}-until`} type='date' value={until} onChange={e => setUntil(e.target.value)} />
        </div>
      </div>
      <label className='flex items-start gap-2'>
        <Checkbox className='mt-0.5' checked={external} onCheckedChange={v => setExternal(v === true)} />
        <span>
          AI 상담에 보내기
          <span className='block text-xs text-muted-foreground'>끄면 이 기억에서 나온 과거 근거도 보내지 않습니다.</span>
        </span>
      </label>
      <div>
        <Button variant='primary' size='sm' disabled={save.isPending || revisions.isPending || !!revisions.error || !content.trim()} onClick={() => save.mutate()}>
          수정본 저장
        </Button>
      </div>
      <QueryStatus pending={revisions.isPending} error={revisions.error} retry={revisions.refetch} label='수정 기록' rows={2} />
      {revisions.data && revisions.data.length > 0 && (
        <div>
          <h4 className='mb-1 text-xs font-semibold text-muted-foreground'>수정 기록</h4>
          <ol className='flex flex-col gap-1.5'>
            {[...revisions.data].reverse().map((r, i) => (
              <li key={r.id} className='border-l-2 pl-2.5 text-ui'>
                <div className='text-xs text-faint'>
                  {i === 0 ? '현재 · ' : ''}
                  {dateTime(r.created_at)} · {r.external_allowed ? '상담에 보냄' : '이 기기에서만'}
                  {(r.valid_from || r.valid_until) && ` · ${r.valid_from ? dateOnly(r.valid_from) : '처음'}부터 ${r.valid_until ? untilLabel(r.valid_until) : '계속'}`}
                </div>
                <p>{r.content}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

/** An end at local midnight means "through the day before". */
function untilLabel(iso: string): string {
  return zonedMinutes(iso) === 0 ? dateOnly(addDays(zonedDayKey(iso), -1)) : dateTime(iso);
}
