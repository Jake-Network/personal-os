'use client';

import { useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import { useParams, useRouter, useSearchParams } from 'next/navigation';

import { notify } from '@/components/notify';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';

import { getListConversationsQueryKey, useDeleteConversation, useGetConversation } from '@/api-client/generated/advisor/advisor';

import { DOMAINS, parseDomain } from '../consts';
import type { InspectorData, InspectorMode } from '../types';
import { AdvisorChat } from './advisor-chat';
import { ContextInspector } from './context-inspector';
import { ConversationList } from './conversation-list';

const WIDE = '(min-width: 1280px)';

/**
 * Rendered from app/(main)/advisor/layout.tsx, not a page: layouts survive /advisor → /advisor/[id],
 * so a new conversation keeps its live answer stream when the URL gains its id.
 */
export function AdvisorWorkspace() {
  const params = useParams<{ id?: string[] }>();
  const search = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const conversationId = params.id?.[0] ? Number(params.id[0]) : null;
  const newDomain = parseDomain(search.get('domain'));

  const [inspector, setInspector] = useState<{ data: InspectorData | null; mode: InspectorMode; loading?: boolean; key: string }>({
    data: null,
    mode: 'preview',
    key: '',
  });
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);

  // Reset the panel when the conversation (or new-conversation domain) changes.
  const viewKey = `${conversationId}:${newDomain}`;
  const inspectorState = inspector.key === viewKey ? inspector : { data: null, mode: 'preview' as const, loading: false };

  const { data: current } = useGetConversation(conversationId ?? 0, undefined, { query: { enabled: conversationId !== null } });
  const domain = parseDomain(current?.domain ?? null) ?? newDomain;

  const remove = useDeleteConversation({
    mutation: {
      onSuccess: () => {
        router.push('/advisor');
        return queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
      },
      onError: notify.error,
    },
  });

  const title = current?.title ?? (domain ? `새 ${DOMAINS.find(d => d.key === domain)?.label ?? ''} 상담` : '새 상담');
  const inspectorProps = { data: inspectorState.data, mode: inspectorState.mode, loading: inspectorState.loading };

  return (
    <div className='grid h-full grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)] xl:grid-cols-[248px_minmax(0,1fr)_320px]'>
      <aside className='hidden min-h-0 flex-col border-r bg-card md:flex'>
        <ConversationList activeId={conversationId} />
      </aside>
      <Sheet open={listOpen} onOpenChange={setListOpen}>
        <SheetContent side='left' className='md:hidden'>
          <SheetTitle className='sr-only'>상담 목록</SheetTitle>
          <ConversationList activeId={conversationId} onNavigate={() => setListOpen(false)} />
        </SheetContent>
      </Sheet>

      <AdvisorChat
        conversationId={conversationId}
        domain={domain}
        onConversationCreated={id => router.replace(`/advisor/${id}`)}
        onInspector={(data, mode, loading) => {
          setInspector({ data, mode, loading, key: viewKey });
          // Below xl the panel is a sheet; open it to show the evidence the user asked for.
          if (mode === 'snapshot' && !window.matchMedia(WIDE).matches) setInspectorOpen(true);
        }}
        header={
          <div className='flex items-center gap-2 border-b bg-card px-[18px] py-3'>
            <h2 className='flex-1 truncate text-[15px]'>{title}</h2>
            <Button size='sm' className='md:hidden' onClick={() => setListOpen(true)}>
              상담 목록
            </Button>
            <Button size='sm' className='xl:hidden' onClick={() => setInspectorOpen(true)}>
              참조 데이터
            </Button>
            {conversationId && (
              <Button
                size='sm'
                variant='destructive'
                disabled={remove.isPending}
                onClick={() => confirm('이 상담과 상담에 사용된 Context Snapshot을 삭제할까요?') && remove.mutate({ conversationId })}>
                삭제
              </Button>
            )}
          </div>
        }
      />

      <ContextInspector {...inspectorProps} className='hidden xl:block' />
      <Sheet open={inspectorOpen} onOpenChange={setInspectorOpen}>
        <SheetContent side='right' className='xl:hidden'>
          <SheetTitle className='sr-only'>참조 중인 데이터</SheetTitle>
          <ContextInspector {...inspectorProps} className='h-full border-l-0' onClose={() => setInspectorOpen(false)} />
        </SheetContent>
      </Sheet>
    </div>
  );
}
