'use client';

import { useRef, useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import { Info, ListTree, MessagesSquare, MoreHorizontal, PanelRight, Trash2 } from 'lucide-react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';

import { getListConversationsQueryKey, useDeleteConversation, useGetConversation } from '@/api-client/generated/advisor/advisor';
import { useConfirm } from '@/components/confirm-dialog';
import { notify } from '@/components/notify';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';

import { DOMAINS, parseDomain } from '../consts';
import type { InspectorData, InspectorMode } from '../types';
import { AdvisorChat } from './advisor-chat';
import { ConversationInfoDialog } from './conversation-info-dialog';
import { ConversationList } from './conversation-list';
import { WorkspacePanel } from './workspace-panel';

const WIDE = '(min-width: 1280px)';

/**
 * The layout owns the selected evidence panel. Each conversation observes its saved server run,
 * so URL changes and chat remounts recover the same execution.
 */
export function AdvisorWorkspace() {
  const params = useParams<{ id?: string[] }>();
  const search = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const conversationId = params.id?.[0] ? Number(params.id[0]) : null;
  const newDomain = parseDomain(search.get('domain'));

  const [inspector, setInspector] = useState<{ data: InspectorData | null; mode: InspectorMode; loading?: boolean; key: string }>({
    data: null,
    mode: 'preview',
    key: '',
  });
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const latestInspector = useRef<typeof inspector | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);

  // Reset the panel when the conversation (or new-conversation domain) changes.
  const viewKey = `${conversationId}:${newDomain}:${conversationId === null ? search.get('document') : ''}`;
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

  const askRemove = async () => {
    if (!conversationId) return;
    const ok = await confirm({
      title: '이 상담을 삭제할까요?',
      description: '질문과 답변, 답변에 쓴 당시 기록 사본이 함께 지워지고 진행 중인 분석은 중지됩니다. 원래 기록과 문서, 이미 승인해 반영한 내용은 그대로 남습니다.',
      confirmLabel: '삭제',
      destructive: true,
    });
    if (ok) remove.mutate({ conversationId });
  };

  const backToCurrent = () => {
    const latest = latestInspector.current;
    setInspector(latest?.key === viewKey ? latest : { data: null, mode: 'preview', key: viewKey });
  };

  const title = current?.title ?? (domain ? `새 ${DOMAINS.find(d => d.key === domain)?.label ?? ''} 상담` : '새 상담');
  const inspectorProps = { data: inspectorState.data, mode: inspectorState.mode, loading: inspectorState.loading };

  return (
    <div className='grid h-full grid-cols-1 md:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[248px_minmax(0,1fr)_340px]'>
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
        key={`chat:${conversationId ?? viewKey}`}
        conversationId={conversationId}
        domain={domain}
        evidenceActive={inspectorState.mode === 'snapshot'}
        onConversationCreated={id => router.replace(`/advisor/${id}`)}
        onInspector={(data, mode, loading) => {
          if (mode !== 'snapshot') latestInspector.current = { data, mode, loading, key: viewKey };
          if (mode !== 'snapshot' && inspector.key === viewKey && inspector.mode === 'snapshot') return;
          setInspector({ data, mode, loading, key: viewKey });
          // Below xl the panel is a sheet; open it to show the evidence the user asked for.
          if (mode === 'snapshot' && !window.matchMedia(WIDE).matches) setInspectorOpen(true);
        }}
        header={
          <div className='flex items-center gap-1 border-b bg-card px-3 py-2 md:px-4'>
            <Button size='icon-sm' variant='ghost' className='md:hidden' aria-label='상담 목록' onClick={() => setListOpen(true)}>
              <MessagesSquare />
            </Button>
            <h2 className='min-w-0 flex-1 truncate text-title font-semibold'>{title}</h2>
            <Button size='icon-sm' variant='ghost' className='xl:hidden' aria-label='근거와 제안 보기' onClick={() => setInspectorOpen(true)}>
              <PanelRight />
            </Button>
            {conversationId && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size='icon-sm' variant='ghost' aria-label='상담 메뉴'>
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onSelect={() => setInfoOpen(true)}>
                    <Info /> 대화 정보
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setInspectorOpen(true)} className='xl:hidden'>
                    <ListTree /> 근거와 제안
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem destructive disabled={remove.isPending} onSelect={() => void askRemove()}>
                    <Trash2 /> 상담 삭제
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        }
      />

      <WorkspacePanel key={`panel:${viewKey}`} conversationId={conversationId} inspector={inspectorProps} onBack={backToCurrent} className='hidden xl:block' />
      <Sheet open={inspectorOpen} onOpenChange={setInspectorOpen}>
        <SheetContent side='right' className='w-[min(380px,100vw)] xl:hidden'>
          <SheetTitle className='sr-only'>근거와 제안</SheetTitle>
          <WorkspacePanel
            key={viewKey}
            conversationId={conversationId}
            inspector={inspectorProps}
            onBack={backToCurrent}
            className='h-full border-l-0'
            onClose={() => setInspectorOpen(false)}
          />
        </SheetContent>
      </Sheet>
      {conversationId && <ConversationInfoDialog conversationId={conversationId} open={infoOpen} onOpenChange={setInfoOpen} />}
    </div>
  );
}
