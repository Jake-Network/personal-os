'use client';

import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { customInstance } from '@/api-client/custom-client';
import type { ConversationDetail } from '@/api-client/model';

import { notify } from '@/components/notify';
import { Markdown } from '@/components/markdown';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { documentsApi, documentsKey, type DocumentCitation } from '@/features/documents/api';
import { RecordSelect } from '@/features/personal-data/components/record-select';

import { Textarea } from '@/components/ui/textarea';

import { ApiError, errorMessage } from '@/api-client/api-error';
import {
  createConversation,
  getGetConversationQueryOptions,
  getGetSnapshotQueryOptions,
  getListConversationsQueryKey,
  previewContext,
} from '@/api-client/generated/advisor/advisor';
import { useGetPrivacy } from '@/api-client/generated/privacy/privacy';
import { useGetStatus } from '@/api-client/generated/ai-provider/ai-provider';
import { getListProposalsQueryKey, useListProposals } from '@/api-client/generated/proposals/proposals';
import type { Category, ConversationCreateDomain } from '@/api-client/model';
import { CATEGORY_HINT, CATEGORY_LABEL, ERROR_HINT } from '@/lib/labels';
import { cn } from '@/lib/utils';
import { dateTime } from '@/lib/utils/format';

import { SUGGESTIONS } from '../consts';
import type { ChatMessage, InspectorData, InspectorMode } from '../types';
import { optionsFor, sameRunIntent, snapshotToInspector, stripBlocks } from '../utils';
import { MemoryProposalCard, ProposalCard } from './proposal-card';
import { ConversationSummary } from './conversation-summary';
import { workspaceApi, workspaceKey } from '../api';
import { isUnfinished, useWorkspace } from '../hooks/use-workspace';
import { RunCard } from './run-card';
import { ScenarioComparison } from './scenario-comparison';
import type { RunCreate } from '@/api-client/model';

interface Props {
  conversationId: number | null;
  domain?: ConversationCreateDomain;
  compact?: boolean;
  header?: ReactNode;
  onConversationCreated?: (id: number) => void;
  onInspector?: (data: InspectorData | null, mode: InspectorMode, loading?: boolean) => void;
}

const SHARE_CATEGORIES: Category[] = ['financial', 'investment', 'career', 'calendar', 'health', 'goals'];

export function AdvisorChat({ conversationId, domain, compact, header, onConversationCreated, onInspector }: Props) {
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
  const hasOlder = !olderExhausted && (history.data?.messages.length ?? 0) >= 100;
  const [input, setInput] = useState('');
  const [historyCompany, setHistoryCompany] = useState('');
  const [historyProject, setHistoryProject] = useState('');
  const [historyDecision, setHistoryDecision] = useState('');
  const [documentSearch, setDocumentSearch] = useState(true);
  const [webSearch, setWebSearch] = useState(false);
  const [webQuery, setWebQuery] = useState('');
  const [documentIds, setDocumentIds] = useState<number[] | null>(() => {
    const id = Number(searchParams.get('document'));
    return !conversationId && Number.isSafeInteger(id) && id > 0 ? [id] : null;
  });
  const [source, setSource] = useState<{ citation?: DocumentCitation; error?: string } | null>(null);
  const documents = useQuery({ queryKey: documentsKey, queryFn: documentsApi.list });
  const [sending, setSending] = useState(false);
  const [depth, setDepth] = useState<'auto' | 'deep'>('auto');
  const workspace = useWorkspace(conversationId);
  const activeRun = workspace.data?.active_run;
  const busy = sending || isUnfinished(activeRun?.status);
  const waiting = activeRun?.status === 'waiting_input' && !!activeRun.clarification;
  const pendingRequest = useRef<{ conversationId: number; body: RunCreate } | null>(null);
  const pendingResponse = useRef<{ key: string; requestId: string } | null>(null);
  const sendLock = useRef(false);
  const createdConversation = useRef<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uncertainRetry, setUncertainRetry] = useState(false);
  const [previewState, setPreviewState] = useState<{ key: string; base?: InspectorData; data?: InspectorData; error?: string } | null>(null);
  const [forcedOn, setForcedOn] = useState<Set<Category>>(new Set());
  const [forcedOff, setForcedOff] = useState<Set<Category>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);
  const followMessages = useRef(true);
  const [newMessages, setNewMessages] = useState(false);
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

  const documentOptions = useMemo(
    () => ({
      document_search: documentSearch,
      document_ids: documentIds,
      history_company: historyCompany || null,
      history_project: historyProject ? Number(historyProject) : null,
      history_decision: historyDecision ? Number(historyDecision) : null,
      web_search: webSearch,
      web_query: webSearch ? webQuery.trim() : null,
    }),
    [documentSearch, documentIds, historyCompany, historyProject, historyDecision, webSearch, webQuery],
  );

  const previewKey = JSON.stringify([input.trim(), conversationId, documentOptions, [...forcedOn], [...forcedOff]]);
  const baseline = previewState?.key === previewKey ? previewState.base : undefined;
  const preview = previewState?.key === previewKey ? previewState.data : undefined;
  const previewError = previewState?.key === previewKey ? previewState.error : undefined;
  const requestOptions = baseline ? optionsFor(baseline, forcedOn, forcedOff) : { exclude: [...forcedOff] };

  // Debounced Context preview while typing (nothing is sent to the model).
  useEffect(() => {
    let current = true;
    const text = input.trim();
    if (busy) return;
    if (!text) {
      onInspectorRef.current?.(workspace.context ?? null, workspace.context ? 'answer' : 'preview');
      return;
    }
    onInspectorRef.current?.(null, 'preview');
    if (text.length < 2 || (webSearch && !webQuery.trim())) return;
    const timer = setTimeout(async () => {
      try {
        const base = (await previewContext({ message: text, conversation_id: conversationId, ...documentOptions })) as InspectorData;
        if (!current) return;
        const adjusted = forcedOn.size || forcedOff.size;
        const final = adjusted
          ? ((await previewContext({
              message: text,
              conversation_id: conversationId,
              ...optionsFor(base, forcedOn, forcedOff),
              ...documentOptions,
            })) as InspectorData)
          : base;
        if (!current) return;
        setPreviewState({ key: previewKey, base, data: final });
        onInspectorRef.current?.(final, 'preview');
      } catch (error) {
        if (current) setPreviewState({ key: previewKey, error: '공유 범위를 미리 확인하지 못했습니다. ' + errorMessage(error) });
      }
    }, 350);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [input, conversationId, forcedOn, forcedOff, busy, documentOptions, webSearch, webQuery, previewKey, workspace.context]);

  function toggle(c: Category) {
    if (privacyBlocked.includes(c) || c === 'profile') return;
    const isOn = preview?.categories.includes(c);
    const on = new Set(forcedOn);
    const off = new Set(forcedOff);
    if (isOn) {
      if (on.has(c)) on.delete(c);
      else off.add(c);
    } else {
      if (off.has(c)) off.delete(c);
      else on.add(c);
    }
    setForcedOn(on);
    setForcedOff(off);
  }

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

  async function send(textArg?: string) {
    const text = (textArg ?? input).trim();
    if (!text || sendLock.current || sending || (busy && !waiting) || providerNeedsSetup) return;
    if (textArg && !waiting && text !== input.trim()) {
      setInput(text);
      return;
    }
    if (!waiting && forcedOn.size > 0 && !baseline) {
      setLoadError('변경한 공유 범위를 확인하는 중입니다. 미리보기가 완료되면 다시 보내 주세요.');
      return;
    }
    if (!waiting && webSearch && !webQuery.trim()) {
      setLoadError('웹 검색에 사용할 공개 검색어를 입력해 주세요.');
      return;
    }
    sendLock.current = true;
    setSending(true);
    setLoadError(null);
    let convId = conversationId ?? createdConversation.current;
    let runSaved = false;
    try {
      if (convId === null) {
        const conv = await createConversation({ title: text.slice(0, 60), domain: domain ?? null });
        convId = conv.id;
        createdConversation.current = conv.id;
        void queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
      }
      if (waiting && activeRun?.clarification) {
        const key = `${activeRun.id}:${activeRun.revision}:${text}`;
        if (pendingResponse.current?.key !== key) pendingResponse.current = { key, requestId: crypto.randomUUID() };
        await workspaceApi.respond(activeRun.id, {
          request_id: pendingResponse.current.requestId,
          question_id: activeRun.clarification.id,
          expected_revision: activeRun.revision,
          response: text,
        });
        pendingResponse.current = null;
      } else {
        const previous = pendingRequest.current;
        const candidate: RunCreate = {
          message: text,
          ...requestOptions,
          ...documentOptions,
          request_id: crypto.randomUUID(),
          depth,
          parent_revision: workspace.data?.revision,
        };
        const sameIntent = previous?.conversationId === convId && sameRunIntent({ ...previous.body }, { ...candidate });
        if (previous?.conversationId === convId && !sameIntent) {
          // Reconcile an uncertain save before creating a request with changed privacy settings.
          const recovered = await workspaceApi.get(convId);
          queryClient.setQueryData(workspaceKey(convId), recovered);
          const accepted = [recovered.active_run, recovered.latest_run].some(run => run?.request_id === previous.body.request_id);
          if (accepted) {
            pendingRequest.current = null;
            showCurrentMessages();
            throw new Error('이전 질문은 이미 접수되었습니다. 현재 답변을 확인한 뒤 변경한 공유 범위로 새 질문을 보내 주세요.');
          }
          if (isUnfinished(recovered.active_run?.status)) throw new Error('진행 중인 상담을 확인한 뒤 다시 보내 주세요.');
          setUncertainRetry(true);
          throw new Error('이전 질문의 접수 여부가 아직 불명확합니다. 변경한 질문을 별도로 보내면 두 요청이 모두 실행될 수 있습니다.');
        }
        const body = sameIntent && previous ? previous.body : candidate;
        pendingRequest.current = { conversationId: convId, body };
        await workspaceApi.createRun(convId, body);
        pendingRequest.current = null;
      }
      runSaved = true;
      setUncertainRetry(false);
      showCurrentMessages();
      setInput('');
      if (!waiting) {
        setWebSearch(false);
        setWebQuery('');
      }
      setForcedOn(new Set());
      setForcedOff(new Set());
      setPreviewState(null);
      await queryClient.invalidateQueries({ queryKey: workspaceKey(convId) });
    } catch (e) {
      // Validation/auth rejection cannot have created this run. Conflict/network/5xx remain uncertain.
      if (e instanceof ApiError && [401, 403, 422].includes(e.status)) pendingRequest.current = null;
      setLoadError(errorMessage(e));
      if (convId) void queryClient.invalidateQueries({ queryKey: workspaceKey(convId) });
      if (conversationId === null && convId !== null) {
        try {
          const recovered = await workspaceApi.get(convId);
          runSaved = !!(recovered.active_run ?? recovered.latest_run);
        } catch {
          /* Keep the draft and request identity for an explicit retry. */
        }
      }
    } finally {
      sendLock.current = false;
      setSending(false);
      if (runSaved && conversationId === null && convId !== null) onConversationCreated?.(convId);
      void queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
      void queryClient.invalidateQueries({ queryKey: getListProposalsQueryKey() });
    }
  }

  async function showEvidence(snapshotId: string | null) {
    if (!snapshotId) return;
    onInspectorRef.current?.(null, 'snapshot', true);
    const snapshot = await queryClient.fetchQuery({ ...getGetSnapshotQueryOptions(snapshotId), staleTime: 0 });
    onInspectorRef.current?.(snapshotToInspector(snapshot), 'snapshot');
  }

  async function showDocument(message: ChatMessage, ref: string) {
    setSource({ error: '근거를 불러오는 중…' });
    try {
      const snapshot = message.context_snapshot_id
        ? await queryClient.fetchQuery({ ...getGetSnapshotQueryOptions(message.context_snapshot_id), staleTime: 0 })
        : null;
      const citations = snapshot ? snapshotToInspector(snapshot).document_citations : message.document_citations;
      const citation = citations?.find(c => c.ref.replace(/^\[|\]$/g, '') === ref);
      setSource(citation ? { citation } : { error: '이 답변의 근거가 삭제되었거나 보관된 발췌문이 없습니다.' });
    } catch (e) {
      setSource({ error: errorMessage(e) });
    }
  }

  const suggestions = SUGGESTIONS[domain ?? 'general'] ?? SUGGESTIONS.general;

  async function loadOlder() {
    const before = messages.find(m => m.id)?.id;
    if (!conversationId || !before) return;
    const requestedView = conversationId;
    setLoadingOlder(true);
    try {
      const detail = await customInstance<ConversationDetail>({ url: `/api/advisor/conversations/${conversationId}`, params: { before_id: before } });
      if (viewRef.current !== requestedView) return;
      setOlderMessages(existing => [...detail.messages.map(m => ({ ...m, key: `m-${m.id}` }) as ChatMessage), ...existing]);
      setOlderExhausted(detail.messages.length < 100);
    } catch (e) {
      notify.error(e);
    } finally {
      setLoadingOlder(false);
    }
  }

  return (
    <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col', compact ? 'bg-card' : 'bg-background')}>
      {header}
      <Dialog
        open={source !== null}
        onOpenChange={open => {
          if (!open) setSource(null);
        }}>
        <DialogContent>
          <DialogTitle>{source?.citation?.title ?? '문서 근거'}</DialogTitle>
          {source?.error && <p>{source.error}</p>}
          {source?.citation && (
            <>
              <p className='text-xs text-faint'>
                {source.citation.filename} · 버전 #{source.citation.version_id}
                {source.citation.page ? ` · p.${source.citation.page}` : ''}
                {source.citation.section ? ` · ${source.citation.section}` : ''}
                {source.citation.as_of ? ` · 기준일 ${source.citation.as_of}` : ''}
              </p>
              <p className='text-xs text-faint'>
                {source.citation.historical ? '이전 상담에서 이어받은 과거 버전의 근거입니다.' : '이 답변에 사용한 당시의 발췌문입니다.'}
              </p>
              <div className='max-h-[60vh] overflow-y-auto whitespace-pre-wrap text-sm'>{source.citation.text}</div>
            </>
          )}
        </DialogContent>
      </Dialog>
      <div
        className={cn('flex flex-1 flex-col overflow-y-auto', compact ? 'gap-3 p-3.5' : 'gap-4 px-[18px] py-5')}
        ref={scrollRef}
        onScroll={e => {
          const el = e.currentTarget;
          followMessages.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
          if (followMessages.current) setNewMessages(false);
        }}>
        {hasOlder && (
          <Button disabled={loadingOlder || sending} onClick={() => void loadOlder()}>
            이전 메시지 더 보기
          </Button>
        )}
        {providerNeedsSetup && (
          <Alert variant='warning'>
            선택한 AI 연결을 설정해야 상담을 시작할 수 있습니다.{' '}
            <Link href='/settings/ai-provider' className='underline'>
              AI 연결 설정하기
            </Link>
          </Alert>
        )}
        {providerStatus.error && (
          <Alert variant='warning'>
            AI 연결 상태를 확인하지 못했습니다.{' '}
            <Link href='/settings/ai-provider' className='underline'>
              연결 설정 확인
            </Link>
          </Alert>
        )}
        {history.error && <Alert variant='destructive'>{errorMessage(history.error)}</Alert>}
        {messages.length === 0 && !loadError && (
          <div className='mx-auto flex w-full max-w-[760px] flex-col items-start gap-2.5'>
            <div className='text-muted-foreground'>공유를 허용한 기록을 바탕으로 상담합니다. 기록이 없거나 부족하면 필요한 내용을 확인합니다.</div>
            {suggestions.map(s => (
              <Button key={s} className='h-auto whitespace-normal py-1.5 text-left' onClick={() => send(s)} disabled={busy || providerNeedsSetup}>
                {s}
              </Button>
            ))}
          </div>
        )}
        {!compact && (
          <details className='border p-3 text-sm'>
            <summary>과거 경험 검색 범위</summary>
            <div className='flex flex-wrap gap-2 py-2'>
              <label>
                회사명
                <input value={historyCompany} onChange={e => setHistoryCompany(e.target.value)} className='block rounded border p-2' />
              </label>
              <label>
                프로젝트
                <RecordSelect
                  fieldName='project_id'
                  aria-label='검색할 프로젝트'
                  value={historyProject}
                  onChange={e => setHistoryProject(e.target.value)}
                  className='block w-28 rounded border p-2'
                />
              </label>
              <label>
                결정
                <RecordSelect
                  fieldName='decision_id'
                  aria-label='검색할 결정'
                  value={historyDecision}
                  onChange={e => setHistoryDecision(e.target.value)}
                  className='block w-28 rounded border p-2'
                />
              </label>
            </div>
          </details>
        )}
        {conversationId && <ConversationSummary conversationId={conversationId} />}
        {messages.map(m => (
          <div key={m.key} id={m.id ? `message-${m.id}` : undefined} className='mx-auto w-full max-w-[760px]'>
            {(m.content || m.streaming) && (
              <div
                className={cn(
                  'rounded-[10px] px-3.5 py-2.5',
                  m.role === 'user' ? 'ml-auto w-fit max-w-[80%] whitespace-pre-wrap bg-accent' : cn('border', compact ? 'bg-background' : 'bg-card'),
                )}>
                {m.role === 'assistant' ? (
                  m.content ? (
                    <div className={m.streaming ? 'typing' : undefined}>
                      <Markdown text={m.streaming ? stripBlocks(m.content) : m.content} onDocumentRef={ref => void showDocument(m, ref)} />
                    </div>
                  ) : (
                    <span className='typing text-xs text-faint'>개인 데이터를 조회하고 답변을 준비하는 중</span>
                  )
                ) : (
                  m.content
                )}
              </div>
            )}
            {m.error && (
              <Alert variant='destructive' className='mt-1.5'>
                <span>{m.error.message}</span>
                {ERROR_HINT[m.error.code] && (
                  <Button asChild size='sm'>
                    <Link href={ERROR_HINT[m.error.code].href}>{ERROR_HINT[m.error.code].action}</Link>
                  </Button>
                )}
              </Alert>
            )}
            <div className={cn('mt-1 flex items-center gap-2 text-[11.5px] text-faint', m.role === 'user' && 'justify-end')}>
              {m.created_at && <span>{dateTime(m.created_at)}</span>}
              {m.status === 'incomplete' && <Badge variant='warning'>미완료 응답</Badge>}
              {m.role === 'user' && m.status === 'failed' && <Badge>답변 없음</Badge>}
              {m.role === 'assistant' && !m.streaming && m.context_snapshot_id && (
                <Button size='sm' variant='ghost' onClick={() => showEvidence(m.context_snapshot_id)}>
                  근거 데이터 보기
                </Button>
              )}
              {m.model && <span>{m.model}</span>}
            </div>
            {m.proposals?.length || m.memoryProposals?.length ? (
              <div className='mt-2 flex flex-col gap-2.5'>
                {m.proposals?.map(p => (
                  <ProposalCard key={p.id} proposal={p} />
                ))}
                {m.memoryProposals?.map(p => (
                  <MemoryProposalCard key={p.id} memory={p} />
                ))}
              </div>
            ) : null}
          </div>
        ))}
        {!!pendingProposals?.length && (
          <div className='mx-auto w-full max-w-[760px]'>
            <div className='mb-1.5 text-xs text-faint'>이 상담의 승인 대기 제안</div>
            <div className='flex flex-col gap-2.5'>
              {pendingProposals.map(p => (
                <ProposalCard key={p.id} proposal={p} />
              ))}
            </div>
          </div>
        )}
        {workspace.run && (
          <RunCard
            run={workspace.run}
            liveText={workspace.liveText}
            progress={workspace.progress}
            progressMessage={workspace.progressMessage}
            reconnecting={workspace.reconnecting}
            onRefresh={workspace.refresh}
            onChoose={text => void send(text)}
          />
        )}
        <ScenarioComparison
          scenarios={(workspace.data?.scenarios ?? [])
            .filter(scenario => (workspace.run?.result?.scenarios as string[] | undefined)?.includes(scenario.id))
            .slice(0, 3)}
        />
      </div>

      <div className={cn('border-t bg-card', compact ? 'px-3 py-2.5' : 'px-[18px] pb-3.5 pt-3')}>
        <div className='mx-auto max-w-[760px]'>
          {newMessages && (
            <Button
              size='sm'
              className='mb-2'
              onClick={() => {
                followMessages.current = true;
                setNewMessages(false);
                scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
              }}>
              새 메시지 보기
            </Button>
          )}
          {loadError && (
            <Alert variant='destructive' className='mb-2'>
              {loadError}
            </Alert>
          )}
          {uncertainRetry && (
            <Button
              className='mb-2'
              disabled={busy}
              onClick={() => {
                pendingRequest.current = null;
                setUncertainRetry(false);
                void send();
              }}>
              변경한 질문을 별도 요청으로 보내기
            </Button>
          )}
          {workspace.error && (
            <Alert variant='destructive' className='mb-2'>
              상담 상태를 확인하지 못했습니다. {errorMessage(workspace.error)}
            </Alert>
          )}
          {previewError && (
            <p role='status' className='mb-2 text-xs text-warning'>
              {previewError}
            </p>
          )}
          {preview && input.trim() && (
            <div className='mb-2 flex flex-wrap items-center gap-1.5' aria-label='이번 질문에 공유할 데이터'>
              <span className='text-xs text-faint'>공유:</span>
              {SHARE_CATEGORIES.map(c => {
                const blocked = privacyBlocked.includes(c);
                const on = preview.categories.includes(c);
                if (!on && !blocked && !forcedOff.has(c) && !preview.excluded_categories.includes(c) && compact) return null;
                return (
                  <button
                    key={c}
                    type='button'
                    className={cn(
                      'cursor-pointer rounded-full border border-input bg-card px-2.5 py-0.5 text-xs text-faint line-through',
                      on && 'border-transparent bg-accent font-semibold text-accent-foreground no-underline',
                      blocked && 'cursor-not-allowed opacity-60',
                    )}
                    title={blocked ? '데이터 공유 설정에서 제외된 영역' : `${CATEGORY_HINT[c]} — 클릭해 ${on ? '제외' : '포함'}`}
                    onClick={() => toggle(c)}
                    aria-pressed={on}>
                    {CATEGORY_LABEL[c]}
                  </button>
                );
              })}
            </div>
          )}
          <details className='mb-2 text-xs'>
            <summary className='cursor-pointer'>
              상담 옵션 · {depth === 'deep' ? '깊게 분석' : '자동 분석'} · 문서{' '}
              {documentSearch ? (documentIds?.length ? `${documentIds.length}개 지정` : '자동 검색') : '검색 끄기'}
            </summary>
            <div className='mt-2 grid gap-2'>
              <label className='flex items-center gap-2'>
                분석 깊이
                <select
                  aria-label='분석 깊이'
                  className='rounded border bg-background p-1'
                  value={depth}
                  disabled={busy}
                  onChange={e => setDepth(e.target.value as 'auto' | 'deep')}>
                  <option value='auto'>자동</option>
                  <option value='deep'>깊게 분석</option>
                </select>
              </label>
              <p className='text-faint'>문서 자동 검색은 이전 질문에서 지정한 문서를 이어받습니다. 범위를 바꾸려면 지정 해제를 누르세요.</p>
              <label className='flex items-center gap-2'>
                <input type='checkbox' checked={documentSearch} disabled={busy} onChange={e => setDocumentSearch(e.target.checked)} />
                문서 검색 사용
              </label>
              <Button size='sm' disabled={busy || !documentSearch} onClick={() => setDocumentIds([])}>
                지정 해제 · 주제에 맞게 자동 검색
              </Button>
              <p className='text-faint'>비교할 문서를 최대 5개 지정하세요. 공유가 허용된 문서에서 검색합니다.</p>
              {documents.error && <p role='alert'>문서 목록을 불러오지 못했습니다.</p>}
              {documents.data
                ?.filter(d => d.sharing_enabled && d.active_version_id)
                .map(d => (
                  <label key={d.id} className='flex items-center gap-2'>
                    <input
                      type='checkbox'
                      checked={documentIds?.includes(d.id) ?? false}
                      disabled={busy || !documentSearch || (!documentIds?.includes(d.id) && (documentIds?.length ?? 0) >= 5)}
                      onChange={e => setDocumentIds(ids => (e.target.checked ? [...(ids ?? []), d.id] : (ids ?? []).filter(id => id !== d.id)))}
                    />
                    {d.title}
                  </label>
                ))}
              <Link className='underline' href='/documents'>
                문서함에서 업로드·공유 관리
              </Link>
            </div>
          </details>
          <div className='mb-2 grid gap-2 text-xs'>
            <label className='flex items-center gap-2'>
              <input type='checkbox' checked={webSearch} disabled={busy} onChange={e => setWebSearch(e.target.checked)} />웹 검색
            </label>
            {webSearch && (
              <label className='grid gap-1'>
                공개 검색어
                <input
                  className='w-full rounded border bg-background p-2 text-sm'
                  value={webQuery}
                  maxLength={300}
                  disabled={busy}
                  onChange={e => setWebQuery(e.target.value)}
                  placeholder='예: 회사명 채용 공고 백엔드 개발자'
                  aria-describedby='web-search-disclosure'
                />
                <span id='web-search-disclosure' className='text-faint'>
                  입력한 공개 검색어만 외부 검색 서비스에 전송하고, 검색된 페이지의 본문을 수집해 답변 근거로 사용합니다. 개인정보는 검색어에 넣지
                  마세요.
                </span>
              </label>
            )}
          </div>
          <div className='flex items-end gap-2'>
            <Textarea
              className='max-h-[200px] min-h-[52px]'
              placeholder={
                waiting
                  ? '위 확인 질문에 답해 주세요'
                  : busy
                    ? '분석 중에도 다음 질문의 초안을 작성할 수 있습니다'
                    : '무엇이든 물어보세요. 예: 지금 퇴사해도 6개월 버틸 수 있을까?'
              }
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send();
                }
              }}
              rows={2}
              aria-label={waiting ? '확인 질문에 답하기' : '질문 입력'}
            />
            <Button
              variant='primary'
              onClick={() => send()}
              disabled={
                !input.trim() ||
                sending ||
                providerNeedsSetup ||
                (busy && !waiting) ||
                (!waiting && webSearch && !webQuery.trim()) ||
                !!workspace.error ||
                (conversationId !== null && workspace.isPending)
              }>
              {sending ? '저장 중…' : waiting ? '답변 제출' : '보내기'}
            </Button>
          </div>
          {!compact && (
            <div className='mt-1.5 text-xs text-faint'>Enter 보내기 · Shift+Enter 줄바꿈 · 질문에 인증정보나 불필요한 개인정보를 넣지 마세요.</div>
          )}
        </div>
      </div>
    </div>
  );
}
