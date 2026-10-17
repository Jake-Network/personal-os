'use client';

import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';

import { Markdown } from '@/components/markdown';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

import { errorMessage } from '@/api-client/api-error';
import { postEventStream } from '@/api-client/event-stream';
import {
  createConversation,
  getGetConversationQueryOptions,
  getGetSnapshotQueryOptions,
  getListConversationsQueryKey,
  previewContext,
} from '@/api-client/generated/advisor/advisor';
import { useGetPrivacy } from '@/api-client/generated/privacy/privacy';
import { getListProposalsQueryKey, useListProposals } from '@/api-client/generated/proposals/proposals';
import type { Category, ConversationCreateDomain } from '@/api-client/model';
import { CATEGORY_HINT, CATEGORY_LABEL, ERROR_HINT } from '@/lib/labels';
import { cn } from '@/lib/utils';
import { dateTime } from '@/lib/utils/format';

import { SUGGESTIONS } from '../consts';
import type { AdvisorEvent, ChatMessage, InspectorData, InspectorMode } from '../types';
import { optionsFor, snapshotToInspector, stripBlocks } from '../utils';
import { MemoryProposalCard, ProposalCard } from './proposal-card';

interface Props {
  conversationId: number | null;
  domain?: ConversationCreateDomain;
  compact?: boolean;
  header?: ReactNode;
  onConversationCreated?: (id: number) => void;
  onInspector?: (data: InspectorData | null, mode: InspectorMode, loading?: boolean) => void;
}

const SHARE_CATEGORIES: Category[] = ['financial', 'investment', 'career', 'calendar', 'health', 'goals'];

let tempKey = 0;
const nextKey = () => `tmp-${++tempKey}`;

export function AdvisorChat({ conversationId, domain, compact, header, onConversationCreated, onInspector }: Props) {
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [baseline, setBaseline] = useState<InspectorData | null>(null);
  const [preview, setPreview] = useState<InspectorData | null>(null);
  const [forcedOn, setForcedOn] = useState<Set<Category>>(new Set());
  const [forcedOff, setForcedOff] = useState<Set<Category>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  const skipLoadFor = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const onInspectorRef = useRef(onInspector);
  useEffect(() => {
    onInspectorRef.current = onInspector;
  });

  const privacyBlocked = useGetPrivacy().data?.excluded_categories ?? [];
  const pendingProposals = useListProposals(
    { status: 'pending' },
    { query: { enabled: conversationId !== null, select: list => list.filter(p => p.conversation_id === conversationId) } },
  ).data;

  // Load history when switching conversations. Local state stays the source of truth while an answer streams.
  useEffect(() => {
    // The conversation we just created mid-send: keep its live stream and local messages.
    if (conversationId !== null && skipLoadFor.current === conversationId) {
      skipLoadFor.current = null;
      return;
    }
    abortRef.current?.abort();
    setLoadError(null);
    setForcedOn(new Set());
    setForcedOff(new Set());
    if (conversationId === null) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    queryClient
      .fetchQuery({ ...getGetConversationQueryOptions(conversationId), staleTime: 0 })
      .then(detail => {
        if (!cancelled) setMessages(detail.messages.map(m => ({ ...m, key: `m-${m.id}` }) as ChatMessage));
      })
      .catch(e => !cancelled && setLoadError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [conversationId, queryClient]);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const requestOptions = useMemo(
    () => (baseline ? optionsFor(baseline, forcedOn, forcedOff) : { exclude: [...forcedOff] }),
    [baseline, forcedOn, forcedOff],
  );

  // Debounced Context preview while typing (nothing is sent to the model).
  useEffect(() => {
    const text = input.trim();
    if (text.length < 2 || sending) {
      if (!text) {
        setBaseline(null);
        setPreview(null);
      }
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const base = (await previewContext({ message: text, conversation_id: conversationId })) as InspectorData;
        setBaseline(base);
        const adjusted = forcedOn.size || forcedOff.size;
        const final = adjusted
          ? ((await previewContext({ message: text, conversation_id: conversationId, ...optionsFor(base, forcedOn, forcedOff) })) as InspectorData)
          : base;
        setPreview(final);
        onInspectorRef.current?.(final, 'preview');
      } catch {
        /* preview is best-effort */
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [input, conversationId, forcedOn, forcedOff, sending]);

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

  async function send(textArg?: string) {
    const text = (textArg ?? input).trim();
    if (!text || sending) return;
    setSending(true);
    let convId = conversationId;
    try {
      if (convId === null) {
        const conv = await createConversation({ title: text.slice(0, 60), domain: domain ?? null });
        convId = conv.id;
        skipLoadFor.current = conv.id;
        onConversationCreated?.(conv.id);
        void queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
      }
    } catch (e) {
      setSending(false);
      setLoadError(errorMessage(e));
      return;
    }

    const userKey = nextKey();
    const botKey = nextKey();
    setMessages(m => [
      ...m,
      { key: userKey, role: 'user', content: text, status: 'complete', context_snapshot_id: null, model: null },
      { key: botKey, role: 'assistant', content: '', status: 'complete', context_snapshot_id: null, model: null, streaming: true },
    ]);
    setInput('');
    const body = textArg ? { message: text } : { message: text, ...requestOptions };
    setForcedOn(new Set());
    setForcedOff(new Set());
    setPreview(null);
    setBaseline(null);

    const patchBot = (fn: (m: ChatMessage) => ChatMessage) => setMessages(list => list.map(m => (m.key === botKey ? fn(m) : m)));

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await postEventStream<AdvisorEvent>(
        `/api/advisor/conversations/${convId}/messages`,
        body,
        event => {
          if (event.type === 'context') {
            // eslint-disable-next-line @typescript-eslint/no-unused-vars -- drop the discriminator
            const { type: _type, ...data } = event;
            onInspectorRef.current?.(data, 'answer');
            patchBot(m => ({ ...m, context_snapshot_id: data.context_snapshot_id }));
          } else if (event.type === 'delta') {
            patchBot(m => ({ ...m, content: m.content + event.text }));
          } else if (event.type === 'done') {
            patchBot(m => ({
              ...m,
              id: event.message_id,
              streaming: false,
              content: stripBlocks(m.content),
              context_snapshot_id: event.context_snapshot_id,
              proposals: event.proposals,
              memoryProposals: event.memory_proposals,
            }));
          } else if (event.type === 'error') {
            patchBot(m => ({
              ...m,
              streaming: false,
              status: m.content ? 'incomplete' : 'failed',
              error: { code: event.code, message: event.message },
            }));
            setMessages(list => list.map(m => (m.key === userKey ? { ...m, status: 'failed' } : m)));
          }
        },
        controller.signal,
      );
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        patchBot(m => ({ ...m, streaming: false, status: 'failed', error: { code: 'network', message: errorMessage(e) } }));
      } else {
        patchBot(m => ({ ...m, streaming: false, status: 'incomplete' }));
      }
    } finally {
      setSending(false);
      abortRef.current = null;
      void queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
      void queryClient.invalidateQueries({ queryKey: getListProposalsQueryKey() });
    }
  }

  async function showEvidence(snapshotId: string | null) {
    if (!snapshotId) return;
    onInspectorRef.current?.(null, 'snapshot', true);
    const snapshot = await queryClient.fetchQuery(getGetSnapshotQueryOptions(snapshotId));
    onInspectorRef.current?.(snapshotToInspector(snapshot), 'snapshot');
  }

  const suggestions = SUGGESTIONS[domain ?? 'general'] ?? SUGGESTIONS.general;

  return (
    <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col', compact ? 'bg-card' : 'bg-background')}>
      {header}
      <div className={cn('flex flex-1 flex-col overflow-y-auto', compact ? 'gap-3 p-3.5' : 'gap-4 px-[18px] py-5')} ref={scrollRef}>
        {loadError && <Alert variant='destructive'>{loadError}</Alert>}
        {messages.length === 0 && !loadError && (
          <div className='mx-auto flex w-full max-w-[760px] flex-col items-start gap-2.5'>
            <div className='text-muted-foreground'>
              Personal OS에 저장된 실제 데이터를 바탕으로 상담합니다. 내 정보를 다시 설명할 필요가 없습니다.
            </div>
            {suggestions.map(s => (
              <Button key={s} className='h-auto whitespace-normal py-1.5 text-left' onClick={() => send(s)} disabled={sending}>
                {s}
              </Button>
            ))}
          </div>
        )}
        {messages.map(m => (
          <div key={m.key} className='mx-auto w-full max-w-[760px]'>
            {(m.content || m.streaming) && (
              <div
                className={cn(
                  'rounded-[10px] px-3.5 py-2.5',
                  m.role === 'user' ? 'ml-auto w-fit max-w-[80%] whitespace-pre-wrap bg-accent' : cn('border', compact ? 'bg-background' : 'bg-card'),
                )}>
                {m.role === 'assistant' ? (
                  m.content ? (
                    <div className={m.streaming ? 'typing' : undefined}>
                      <Markdown text={m.streaming ? stripBlocks(m.content) : m.content} />
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
      </div>

      <div className={cn('border-t bg-card', compact ? 'px-3 py-2.5' : 'px-[18px] pb-3.5 pt-3')}>
        <div className='mx-auto max-w-[760px]'>
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
          <div className='flex items-end gap-2'>
            <Textarea
              className='max-h-[200px] min-h-[52px]'
              placeholder='무엇이든 물어보세요. 예: 지금 퇴사해도 6개월 버틸 수 있을까?'
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send();
                }
              }}
              rows={2}
              aria-label='질문 입력'
            />
            {sending ? (
              <Button onClick={() => abortRef.current?.abort()}>중지</Button>
            ) : (
              <Button variant='primary' onClick={() => send()} disabled={!input.trim()}>
                보내기
              </Button>
            )}
          </div>
          {!compact && <div className='mt-1.5 text-xs text-faint'>Enter 보내기 · Shift+Enter 줄바꿈 · 계좌번호·인증정보는 전송되지 않습니다</div>}
        </div>
      </div>
    </div>
  );
}
