'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import type { SummaryItem } from '@/api-client/model';
import { Button } from '@/components/ui/button';
import { notify } from '@/components/notify';
import { ConversationLinks } from './conversation-links';

export function ConversationSummary({ conversationId }: { conversationId: number }) {
  const client = useQueryClient();
  const url = `/api/advisor/conversations/${conversationId}/summaries`;
  const list = useQuery({ queryKey: [url], queryFn: () => customInstance<SummaryItem[]>({ url }) });
  const create = useMutation({
    mutationFn: () => customInstance({ url, method: 'POST', data: {} }),
    onSuccess: () => client.invalidateQueries({ queryKey: [url] }),
    onError: notify.error,
  });
  return (
    <details className='border-b bg-card p-3 text-sm'>
      <summary>대화 요약 · 출처</summary>
      <p className='my-2 text-faint'>완료된 원문을 발췌한 로컬 초안입니다. 새 사실이나 확정된 기억으로 취급하지 않습니다.</p>
      <Button size='sm' disabled={create.isPending} onClick={() => create.mutate()}>
        요약 초안 만들기
      </Button>
      {list.error && <p role='alert'>{list.error.message}</p>}
      {list.data?.map(s => (
        <article key={s.id} className='mt-3 border-t pt-2'>
          <p>
            초안 · 메시지 {s.first_message_id}–{s.last_message_id} · {s.generator}
          </p>
          <p className='whitespace-pre-wrap'>{s.content}</p>
        </article>
      ))}
      <ConversationLinks conversationId={conversationId} />
    </details>
  );
}
