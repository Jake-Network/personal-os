'use client';

import { useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { X } from 'lucide-react';

import { customInstance } from '@/api-client/custom-client';
import type { ConversationLinkItem, SummaryItem } from '@/api-client/model';
import { notify } from '@/components/notify';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { dateTime } from '@/lib/utils/format';

import { RecordSelect } from '@/features/personal-data/components/record-select';

const LINK_KIND: Record<ConversationLinkItem['kind'], string> = { company: '회사', project: '프로젝트', decision: '결정' };

function Summaries({ conversationId }: { conversationId: number }) {
  const client = useQueryClient();
  const url = `/api/advisor/conversations/${conversationId}/summaries`;
  const list = useQuery({ queryKey: [url], queryFn: () => customInstance<SummaryItem[]>({ url }) });
  const create = useMutation({
    mutationFn: () => customInstance({ url, method: 'POST', data: {} }),
    onSuccess: () => client.invalidateQueries({ queryKey: [url] }),
    onError: notify.error,
  });
  return (
    <section className='flex flex-col gap-2'>
      <div className='flex items-center gap-2'>
        <h3 className='flex-1 text-ui font-semibold'>요약</h3>
        <Button size='sm' disabled={create.isPending} onClick={() => create.mutate()}>
          요약 만들기
        </Button>
      </div>
      <p className='text-xs text-faint'>대화에서 발췌한 초안입니다. 확인된 사실이나 기억으로 쓰지 않습니다.</p>
      {list.error && <Alert variant='destructive'>요약을 불러오지 못했습니다.</Alert>}
      {list.data?.length === 0 && <p className='text-ui text-muted-foreground'>아직 요약이 없습니다.</p>}
      {list.data?.map(s => (
        <article key={s.id} className='rounded-md border bg-background p-2.5'>
          <p className='mb-1 text-2xs text-faint'>{dateTime(s.created_at)} 작성</p>
          <p className='whitespace-pre-wrap text-ui'>{s.content}</p>
        </article>
      ))}
    </section>
  );
}

function Links({ conversationId }: { conversationId: number }) {
  const client = useQueryClient();
  const url = `/api/advisor/conversations/${conversationId}/links`;
  const [kind, setKind] = useState<ConversationLinkItem['kind']>('company');
  const [target, setTarget] = useState('');
  const list = useQuery({ queryKey: [url], queryFn: () => customInstance<ConversationLinkItem[]>({ url }) });
  const mutate = useMutation({
    mutationFn: (id?: number) => customInstance({ url: id ? `${url}/${id}` : url, method: id ? 'DELETE' : 'POST', data: id ? undefined : { kind, target } }),
    onSuccess: () => {
      setTarget('');
      return client.invalidateQueries({ queryKey: [url] });
    },
    onError: notify.error,
  });
  return (
    <section className='flex flex-col gap-2'>
      <h3 className='text-ui font-semibold'>연결</h3>
      <p className='text-xs text-faint'>회사·프로젝트·결정에 연결하면 나중에 과거 경험으로 찾을 수 있습니다.</p>
      <div className='flex flex-wrap gap-1.5'>
        {list.data?.map(link => (
          <span key={link.id} className='inline-flex items-center gap-1 rounded-full border bg-muted py-0.5 pl-2.5 pr-1 text-xs'>
            {LINK_KIND[link.kind]} · {link.target}
            <button
              type='button'
              aria-label={`${link.target} 연결 해제`}
              disabled={mutate.isPending}
              onClick={() => mutate.mutate(link.id)}
              className='rounded-full p-0.5 hover:bg-card'>
              <X className='size-3' />
            </button>
          </span>
        ))}
      </div>
      {list.error && <Alert variant='destructive'>연결을 불러오지 못했습니다.</Alert>}
      <form
        className='flex flex-wrap items-end gap-2'
        onSubmit={e => {
          e.preventDefault();
          mutate.mutate(undefined);
        }}>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='link-kind'>종류</Label>
          <NativeSelect
            id='link-kind'
            value={kind}
            onChange={e => {
              setKind(e.target.value as typeof kind);
              setTarget('');
            }}>
            <option value='company'>회사</option>
            <option value='project'>프로젝트</option>
            <option value='decision'>결정</option>
          </NativeSelect>
        </div>
        <div className='flex min-w-40 flex-1 flex-col gap-1'>
          <Label htmlFor='link-target'>{LINK_KIND[kind]}</Label>
          {kind === 'company' ? (
            <Input id='link-target' required value={target} onChange={e => setTarget(e.target.value)} placeholder='회사명' />
          ) : (
            <RecordSelect id='link-target' fieldName={kind === 'project' ? 'project_id' : 'decision_id'} required value={target} onChange={e => setTarget(e.target.value)} />
          )}
        </div>
        <Button type='submit' disabled={mutate.isPending}>
          연결
        </Button>
      </form>
    </section>
  );
}

function HistoryIndex() {
  const index = useMutation({ mutationFn: () => customInstance({ url: '/api/advisor/history/index', method: 'POST' }), onError: notify.error });
  return (
    <section className='flex flex-col gap-2'>
      <h3 className='text-ui font-semibold'>과거 상담 검색 준비</h3>
      <p className='text-xs text-faint'>지난 상담을 뜻으로도 찾을 수 있게 이 기기에서 정리합니다(한 번에 메시지 100개). 정리 전이거나 실패하면 단어로만 찾습니다.</p>
      <Button size='sm' className='self-start' disabled={index.isPending} onClick={() => index.mutate()}>
        {index.isPending ? '정리하는 중…' : '지금 정리하기'}
      </Button>
      {index.isSuccess && <p className='text-xs text-success'>정리했습니다.</p>}
    </section>
  );
}

/** Tools about a conversation that are not part of reading it: summaries, links, search preparation. */
export function ConversationInfoDialog({ conversationId, open, onOpenChange }: { conversationId: number; open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>대화 정보</DialogTitle>
        </DialogHeader>
        {open && (
          <div className='flex flex-col gap-5'>
            <Summaries conversationId={conversationId} />
            <Links conversationId={conversationId} />
            <HistoryIndex />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
