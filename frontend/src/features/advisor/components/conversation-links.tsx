'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import type { ConversationLinkItem } from '@/api-client/model';
import { Button } from '@/components/ui/button';
import { notify } from '@/components/notify';
import { RecordSelect } from '@/features/personal-data/components/record-select';

export function ConversationLinks({ conversationId }: { conversationId: number }) {
  const client = useQueryClient();
  const url = `/api/advisor/conversations/${conversationId}/links`;
  const [kind, setKind] = useState<'company' | 'project' | 'decision'>('company');
  const [target, setTarget] = useState('');
  const list = useQuery({ queryKey: [url], queryFn: () => customInstance<ConversationLinkItem[]>({ url }) });
  const mutate = useMutation({
    mutationFn: (id?: number) =>
      customInstance({ url: id ? `${url}/${id}` : url, method: id ? 'DELETE' : 'POST', data: id ? undefined : { kind, target } }),
    onSuccess: () => client.invalidateQueries({ queryKey: [url] }),
    onError: notify.error,
  });
  const index = useMutation({ mutationFn: () => customInstance({ url: '/api/advisor/history/index', method: 'POST' }), onError: notify.error });
  return (
    <div className='mt-3 space-y-2 border-t pt-3'>
      <form
        className='flex flex-wrap gap-2'
        onSubmit={e => {
          e.preventDefault();
          mutate.mutate(undefined);
        }}>
        <select
          aria-label='연결 종류'
          value={kind}
          onChange={e => {
            setKind(e.target.value as typeof kind);
            setTarget('');
          }}
          className='rounded border p-2'>
          <option value='company'>회사</option>
          <option value='project'>프로젝트</option>
          <option value='decision'>결정</option>
        </select>
        {kind === 'company' ? (
          <input
            aria-label='회사명'
            required
            value={target}
            onChange={e => setTarget(e.target.value)}
            placeholder='회사명'
            className='rounded border p-2'
          />
        ) : (
          <RecordSelect
            fieldName={kind === 'project' ? 'project_id' : 'decision_id'}
            required
            aria-label={kind === 'project' ? '연결할 프로젝트' : '연결할 결정'}
            value={target}
            onChange={e => setTarget(e.target.value)}
          />
        )}
        <Button disabled={mutate.isPending}>대화 연결</Button>
      </form>
      {list.data?.map(link => (
        <Button key={link.id} size='sm' disabled={mutate.isPending} onClick={() => mutate.mutate(link.id)}>
          {link.kind}: {link.target} · 연결 해제
        </Button>
      ))}
      {list.error && <p role='alert'>{list.error.message}</p>}
      <p className='text-faint'>로컬 임베딩 색인이 없거나 실패하면 키워드 검색으로 제한하고 상담 근거에 표시합니다.</p>
      <Button size='sm' disabled={index.isPending} onClick={() => index.mutate()}>
        로컬 검색 색인 만들기 (최대 100개)
      </Button>
      {index.isSuccess && <p>색인 작업을 완료했습니다. 다음 묶음은 서버의 after_id 범위로 재개할 수 있습니다.</p>}
    </div>
  );
}
