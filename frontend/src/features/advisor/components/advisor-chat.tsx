'use client';

import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import { errorMessage } from '@/api-client/api-error';
import { customInstance } from '@/api-client/custom-client';
import { getGetConversationQueryOptions, getGetSnapshotQueryOptions } from '@/api-client/generated/advisor/advisor';
import { useGetStatus } from '@/api-client/generated/ai-provider/ai-provider';
import { useGetPrivacy } from '@/api-client/generated/privacy/privacy';
import { useListProposals } from '@/api-client/generated/proposals/proposals';
import type { ConversationCreateDomain, ConversationDetail } from '@/api-client/model';
import { notify } from '@/components/notify';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { SUGGESTIONS } from '../consts';
import { useAdvisorSend } from '../hooks/use-advisor-send';
import { useWorkspace } from '../hooks/use-workspace';
import type { ChatMessage, InspectorData, InspectorMode, MemoryProposal } from '../types';
import { snapshotToInspector } from '../utils';
import { answerQuestion, briefingDraft } from '../utils/answer-actions';
import { AdvisorEmptyState } from './advisor-empty-state';
import { Composer } from './composer';
import { MessageItem, useDocumentSource } from './message-list';
import { MemoryProposalCard, ProposalCard } from './proposal-card';
import { RunStatus } from './run-status';
import { ScenarioComparison } from './scenario-comparison';

interface Props {
  conversationId: number | null;
  domain?: ConversationCreateDomain;
  compact?: boolean;
  header?: ReactNode;
  onConversationCreated?: (id: number) => void;
  onInspector?: (data: InspectorData | null, mode: InspectorMode, loading?: boolean) => void;
  /** The evidence panel currently shows an answer's saved data; its message is highlighted. */
  evidenceActive?: boolean;
}

const PAGE = 100;

export function AdvisorChat({ conversationId, domain, compact, header, onConversationCreated, onInspector, evidenceActive }: Props) {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const targetMessage = Number(searchParams.get('message')) || null;
  const [historyView, setHistoryView] = useState({ target: targetMessage, latest: false });
  if (historyView.target !== targetMessage) setHistoryView({ target: targetMessage, latest: false });
  const showLatest = historyView.target === targetMessage && historyView.latest;
  const messageAnchor = useRef<number | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderExhausted, setOlderExhausted] = useState(false);
  const viewRef = useRef(conversationId);
  useEffect(() => {
    viewRef.current = conversationId;
  }, [conversationId]);
  const [olderMessages, setOlderMessages] = useState<ChatMessage[]>([]);
  const history = useQuery({
    ...getGetConversationQueryOptions(conversationId ?? 0, targetMessage && !showLatest ? { before_id: targetMessage + 1 } : undefined),
    enabled: conversationId !== null,
  });
  const messages = useMemo(() => {
    const fetched = (history.data?.messages ?? []).map(message => ({ ...message, key: `m-${message.id}` }) as ChatMessage);
    return [...new Map([...olderMessages, ...fetched].map(message => [message.id, message])).values()].sort(
      (left, right) => (left.id ?? 0) - (right.id ?? 0),
    );
  }, [olderMessages, history.data?.messages]);
  const hasOlder = !olderExhausted && (history.data?.messages.length ?? 0) >= PAGE;

  const workspace = useWorkspace(conversationId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const followMessages = useRef(true);
  const [newMessages, setNewMessages] = useState(false);
  const [evidenceFor, setEvidenceFor] = useState<string | null>(null);
  const onInspectorRef = useRef(onInspector);
  useEffect(() => {
    onInspectorRef.current = onInspector;
  });
  useEffect(() => {
    if (workspace.context) onInspectorRef.current?.(workspace.context, 'answer');
  }, [workspace.context]);

  const privacyBlocked = useGetPrivacy().data?.excluded_categories ?? [];
  const providerStatus = useGetStatus();
  const provider = providerStatus.data;
  const providerNeedsSetup =
    provider?.provider === 'codex_app_server' || (provider?.provider === 'chatgpt_plan' && (!provider.connected || !provider.plan_usage_enabled));
  const pendingProposals = useListProposals(
    { status: 'pending' },
    { query: { enabled: conversationId !== null, select: list => list.filter(p => p.conversation_id === conversationId) } },
  ).data;

  function showCurrentMessages() {
    messageAnchor.current = null;
    setHistoryView({ target: targetMessage, latest: true });
    followMessages.current = true;
    setNewMessages(false);
    if (searchParams.has('message')) {
      const params = new URLSearchParams(searchParams.toString());
      params.delete('message');
      router.replace(`${pathname}${params.size ? `?${params}` : ''}`, { scroll: false });
    }
  }

  const send = useAdvisorSend({
    conversationId,
    domain,
    documentParam: searchParams.get('document'),
    workspace,
    providerNeedsSetup,
    privacyBlocked,
    onInspector: (data, mode, loading) => onInspectorRef.current?.(data, mode, loading),
    onConversationCreated,
    onSaved: showCurrentMessages,
  });

  const briefing = searchParams.get('briefing');
  const setInput = send.setInput;
  const appliedBriefing = useRef<string | null>(null);
  useEffect(() => {
    if (!briefing || appliedBriefing.current === briefing) return;
    appliedBriefing.current = briefing;
    setInput(current => briefingDraft(briefing, current));
  }, [briefing, setInput]);

  useEffect(() => {
    const target =
      targetMessage && !showLatest && messageAnchor.current !== targetMessage ? document.getElementById(`message-${targetMessage}`) : null;
    if (target) {
      target.scrollIntoView({ block: 'center' });
      messageAnchor.current = targetMessage;
      followMessages.current = false;
    } else if (followMessages.current) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
    else setNewMessages(true);
  }, [messages, targetMessage, showLatest, workspace.liveText, workspace.progress, workspace.run?.status]);

  async function showEvidence(message: ChatMessage) {
    if (!message.context_snapshot_id) return;
    setEvidenceFor(message.key);
    onInspectorRef.current?.(null, 'snapshot', true);
    try {
      const snapshot = await queryClient.fetchQuery({ ...getGetSnapshotQueryOptions(message.context_snapshot_id), staleTime: 0 });
      onInspectorRef.current?.({ ...snapshotToInspector(snapshot), model: message.model }, 'snapshot');
    } catch (e) {
      notify.error(e);
    }
  }
  const documentSource = useDocumentSource();

  async function loadOlder() {
    const before = messages.find(m => m.id)?.id;
    if (!conversationId || !before) return;
    const requestedView = conversationId;
    setLoadingOlder(true);
    try {
      const detail = await customInstance<ConversationDetail>({ url: `/api/advisor/conversations/${conversationId}`, params: { before_id: before } });
      if (viewRef.current !== requestedView) return;
      setOlderMessages(existing => [...detail.messages.map(m => ({ ...m, key: `m-${m.id}` }) as ChatMessage), ...existing]);
      setOlderExhausted(detail.messages.length < PAGE);
    } catch (e) {
      notify.error(e);
    } finally {
      setLoadingOlder(false);
    }
  }

  const suggestions = SUGGESTIONS[domain ?? 'general'] ?? SUGGESTIONS.general;
  const inlineIds = new Set(messages.flatMap(m => m.proposals?.map(p => p.id) ?? []));
  const pending = (pendingProposals ?? []).filter(p => !inlineIds.has(p.id));
  const runMemories = (Array.isArray(workspace.run?.result?.memory_proposals) ? workspace.run.result.memory_proposals : []) as MemoryProposal[];
  const scenarios = (workspace.data?.scenarios ?? [])
    .filter(scenario => (workspace.run?.result?.scenarios as string[] | undefined)?.includes(scenario.id))
    .slice(0, 3);

  return (
    <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col', compact ? 'bg-card' : 'bg-background')}>
      {header}
      {documentSource.dialog}
      <div
        className={cn('flex flex-1 flex-col overflow-y-auto', compact ? 'gap-3 p-3.5' : 'gap-4 px-4 py-5 md:px-5')}
        ref={scrollRef}
        onScroll={e => {
          const el = e.currentTarget;
          followMessages.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
          if (followMessages.current) setNewMessages(false);
        }}>
        {hasOlder && (
          <Button size='sm' variant='ghost' className='self-center' disabled={loadingOlder || send.sending} onClick={() => void loadOlder()}>
            이전 대화 더 보기
          </Button>
        )}
        {providerNeedsSetup && (
          <Alert variant='warning' className='mx-auto w-full max-w-[760px]'>
            <span className='flex-1'>상담을 시작하려면 AI 연결이 필요합니다.</span>
            <Button asChild size='sm'>
              <Link href='/settings/ai-provider'>AI 연결하기</Link>
            </Button>
          </Alert>
        )}
        {providerStatus.error && (
          <Alert variant='warning' className='mx-auto w-full max-w-[760px]'>
            <span className='flex-1'>AI 연결 상태를 확인하지 못했습니다.</span>
            <Button asChild size='sm'>
              <Link href='/settings/ai-provider'>연결 확인</Link>
            </Button>
          </Alert>
        )}
        {history.error && <Alert variant='destructive'>{errorMessage(history.error)}</Alert>}
        {messages.length === 0 && !send.loadError && (conversationId === null || history.isSuccess) && (
          <AdvisorEmptyState
            suggestions={suggestions}
            excluded={privacyBlocked}
            disabled={send.busy || providerNeedsSetup}
            onPick={text => void send.send(text)}
          />
        )}
        {messages.map(m => (
          <MessageItem
            key={m.key}
            message={m}
            compact={compact}
            conversationId={conversationId}
            question={m.source_question ?? (m.id ? answerQuestion(messages, m.id) : '')}
            highlighted={evidenceActive && evidenceFor === m.key}
            onEvidence={message => void showEvidence(message)}
            onDocument={(message, ref) => void documentSource.show(message, ref)}
          />
        ))}
        {workspace.run && (
          <RunStatus
            run={workspace.run}
            liveText={workspace.liveText}
            progress={workspace.progress}
            progressMessage={workspace.progressMessage}
            reconnecting={workspace.reconnecting}
            onRefresh={workspace.refresh}
            onChoose={text => void send.send(text)}
          />
        )}
        <ScenarioComparison scenarios={scenarios} />
        {(pending.length > 0 || runMemories.length > 0) && (
          <div className='mx-auto flex w-full max-w-[760px] flex-col gap-2.5'>
            {pending.map(p => (
              <ProposalCard key={p.id} proposal={p} />
            ))}
            {runMemories.map(memory => (
              <MemoryProposalCard key={memory.id} memory={memory} />
            ))}
          </div>
        )}
      </div>

      <Composer
        send={send}
        compact={compact}
        privacyBlocked={privacyBlocked}
        workspaceError={workspace.error ? errorMessage(workspace.error) : null}
        newMessages={newMessages}
        onShowNew={() => {
          followMessages.current = true;
          setNewMessages(false);
          scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
        }}
      />
    </div>
  );
}
