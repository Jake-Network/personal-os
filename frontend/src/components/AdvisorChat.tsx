import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { api, postEventStream } from '../api/client';
import type {
  AdvisorEvent,
  Category,
  ConversationDetail,
  InspectorData,
  Memory,
  Message,
  Proposal,
  Snapshot,
} from '../api/types';
import { CATEGORY_HINT, CATEGORY_LABEL, ERROR_HINT } from '../lib/labels';
import { dateTime } from '../lib/format';
import { Markdown } from './Markdown';
import { MemoryProposalCard, ProposalCard } from './ProposalCard';

export type InspectorMode = 'preview' | 'answer' | 'snapshot';

interface ChatMessage extends Omit<Message, 'id' | 'conversation_id' | 'created_at'> {
  key: string;
  id?: number;
  created_at?: string;
  streaming?: boolean;
  error?: { code: string; message: string };
  proposals?: Proposal[];
  memoryProposals?: Pick<Memory, 'id' | 'kind' | 'content'>[];
}

interface Props {
  conversationId: number | null;
  domain?: string | null;
  compact?: boolean;
  header?: ReactNode;
  onConversationCreated?: (id: number) => void;
  onInspector?: (data: InspectorData | null, mode: InspectorMode, loading?: boolean) => void;
}

export const SUGGESTIONS: Record<string, string[]> = {
  general: [
    '현재 내 순자산은?',
    '지금 회사를 퇴사하고 3개월 쉬어도 재정적으로 괜찮을까?',
    '앞으로 6개월 동안 돈, 커리어, 운동을 고려해서 우선순위를 정해 줘',
  ],
  financial: ['현재 내 순자산은?', '월 저축액을 50만원 늘리면 목표 자산 달성이 얼마나 빨라질까?'],
  investment: ['현재 포트폴리오가 너무 공격적인지 분석해 줘', '환율이 10% 떨어지면 내 자산은 어떻게 변해?'],
  career: ['현재 진행 중인 채용 중에서 어떤 회사에 가장 집중해야 할까?', '면접 준비 우선순위를 정리해 줘'],
  calendar: ['다음 주 일정을 분석해서 면접 준비와 운동을 어떻게 병행할지 정리해 줘'],
  health: ['이번 달 운동량이 목표에 비해 충분한지 봐 줘'],
};

let tempKey = 0;
const nextKey = () => `tmp-${++tempKey}`;

export function AdvisorChat({ conversationId, domain, compact, header, onConversationCreated, onInspector }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingProposals, setPendingProposals] = useState<Proposal[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [privacyBlocked, setPrivacyBlocked] = useState<Category[]>([]);
  const [baseline, setBaseline] = useState<InspectorData | null>(null);
  const [forcedOn, setForcedOn] = useState<Set<Category>>(new Set());
  const [forcedOff, setForcedOff] = useState<Set<Category>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  const skipLoadFor = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const onInspectorRef = useRef(onInspector);
  onInspectorRef.current = onInspector;

  // Load history when switching conversations.
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
      setPendingProposals([]);
      return;
    }
    let cancelled = false;
    Promise.all([
      api<ConversationDetail>(`/api/advisor/conversations/${conversationId}`),
      api<Proposal[]>('/api/proposals?status=pending'),
    ])
      .then(([detail, proposals]) => {
        if (cancelled) return;
        setMessages(detail.messages.map((m) => ({ ...m, key: `m-${m.id}` })));
        setPendingProposals(proposals.filter((p) => p.conversation_id === conversationId));
      })
      .catch((e) => !cancelled && setLoadError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    api<{ excluded_categories: Category[] }>('/api/settings/privacy')
      .then((p) => setPrivacyBlocked(p.excluded_categories))
      .catch(() => {});
    return () => abortRef.current?.abort();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  // Per-request sharing: start from what the router picks, then apply the user's toggles.
  const requestOptions = useMemo(
    () => (baseline ? optionsFor(baseline, forcedOn, forcedOff) : { exclude: [...forcedOff] }),
    [baseline, forcedOn, forcedOff],
  );

  // Debounced Context preview while typing (nothing is sent to the model).
  const [preview, setPreview] = useState<InspectorData | null>(null);
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
        const base = await api<InspectorData>('/api/advisor/context/preview', {
          body: { message: text, conversation_id: conversationId },
        });
        setBaseline(base);
        const adjusted = forcedOn.size || forcedOff.size;
        const final = adjusted
          ? await api<InspectorData>('/api/advisor/context/preview', {
              body: { message: text, conversation_id: conversationId, ...optionsFor(base, forcedOn, forcedOff) },
            })
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
        const conv = await api<{ id: number }>('/api/advisor/conversations', {
          body: { title: text.slice(0, 60), domain: domain ?? null },
        });
        convId = conv.id;
        skipLoadFor.current = conv.id;
        onConversationCreated?.(conv.id);
      }
    } catch (e) {
      setSending(false);
      setLoadError((e as Error).message);
      return;
    }

    const userKey = nextKey();
    const botKey = nextKey();
    setMessages((m) => [
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

    const patchBot = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((list) => list.map((m) => (m.key === botKey ? fn(m) : m)));

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await postEventStream(
        `/api/advisor/conversations/${convId}/messages`,
        body,
        (event: AdvisorEvent) => {
          if (event.type === 'context') {
            const { type: _t, ...data } = event;
            onInspectorRef.current?.(data, 'answer');
            patchBot((m) => ({ ...m, context_snapshot_id: data.context_snapshot_id }));
          } else if (event.type === 'delta') {
            patchBot((m) => ({ ...m, content: m.content + event.text }));
          } else if (event.type === 'done') {
            patchBot((m) => ({
              ...m,
              id: event.message_id,
              streaming: false,
              content: stripBlocks(m.content),
              context_snapshot_id: event.context_snapshot_id,
              proposals: event.proposals,
              memoryProposals: event.memory_proposals,
            }));
          } else if (event.type === 'error') {
            patchBot((m) => ({
              ...m,
              streaming: false,
              status: m.content ? 'incomplete' : 'failed',
              error: { code: event.code, message: event.message },
            }));
            setMessages((list) => list.map((m) => (m.key === userKey ? { ...m, status: 'failed' } : m)));
          }
        },
        controller.signal,
      );
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        patchBot((m) => ({ ...m, streaming: false, status: 'failed', error: { code: 'network', message: (e as Error).message } }));
      } else {
        patchBot((m) => ({ ...m, streaming: false, status: 'incomplete' }));
      }
    } finally {
      setSending(false);
      abortRef.current = null;
    }
  }

  async function showEvidence(snapshotId: string | null) {
    if (!snapshotId) return;
    onInspectorRef.current?.(null, 'snapshot', true);
    const s = await api<Snapshot>(`/api/advisor/snapshots/${snapshotId}`);
    onInspectorRef.current?.(
      {
        context_snapshot_id: s.context_snapshot_id,
        context_reused: false,
        categories: s.context_categories,
        excluded_categories: s.excluded_categories,
        source_updated_at: s.source_updated_at,
        record_references: s.record_references,
        data_quality_flags: s.data_quality_flags,
      },
      'snapshot',
    );
  }

  const suggestions = SUGGESTIONS[domain ?? 'general'] ?? SUGGESTIONS.general;
  const chipCats = (['financial', 'investment', 'career', 'calendar', 'health', 'goals'] as Category[]);

  return (
    <div className={`chat${compact ? ' compact' : ''}`}>
      {header}
      <div className="chat-scroll" ref={scrollRef}>
        {loadError && <div className="banner danger">{loadError}</div>}
        {messages.length === 0 && !loadError && (
          <div className="msg">
            <div className="stack" style={{ alignItems: 'flex-start' }}>
              <div className="muted">
                Personal OS에 저장된 실제 데이터를 바탕으로 상담합니다. 내 정보를 다시 설명할 필요가 없습니다.
              </div>
              {suggestions.map((s) => (
                <button key={s} className="btn" onClick={() => send(s)} disabled={sending}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.key} className={`msg ${m.role}`}>
            {(m.content || m.streaming) && (
              <div className="bubble">
                {m.role === 'assistant' ? (
                  m.content ? (
                    <div className={m.streaming ? 'typing' : ''}>
                      <Markdown text={m.streaming ? stripBlocks(m.content) : m.content} />
                    </div>
                  ) : (
                    <span className="faint typing">개인 데이터를 조회하고 답변을 준비하는 중</span>
                  )
                ) : (
                  m.content
                )}
              </div>
            )}
            {m.error && (
              <div className="banner danger" style={{ marginTop: 6 }}>
                <span>{m.error.message}</span>
                {ERROR_HINT[m.error.code] && (
                  <Link to={ERROR_HINT[m.error.code].to} className="btn sm">{ERROR_HINT[m.error.code].action}</Link>
                )}
              </div>
            )}
            <div className="meta">
              {m.created_at && <span>{dateTime(m.created_at)}</span>}
              {m.status === 'incomplete' && <span className="chip warn">미완료 응답</span>}
              {m.role === 'user' && m.status === 'failed' && <span className="chip">답변 없음</span>}
              {m.role === 'assistant' && !m.streaming && m.context_snapshot_id && (
                <button className="btn sm ghost" onClick={() => showEvidence(m.context_snapshot_id)}>근거 데이터 보기</button>
              )}
              {m.model && <span>{m.model}</span>}
            </div>
            {(m.proposals?.length || m.memoryProposals?.length) ? (
              <div className="stack" style={{ marginTop: 8 }}>
                {m.proposals?.map((p) => <ProposalCard key={p.id} proposal={p} />)}
                {m.memoryProposals?.map((p) => <MemoryProposalCard key={p.id} memory={p} />)}
              </div>
            ) : null}
          </div>
        ))}
        {pendingProposals.length > 0 && (
          <div className="msg">
            <div className="faint" style={{ marginBottom: 6 }}>이 상담의 승인 대기 제안</div>
            <div className="stack">
              {pendingProposals.map((p) => <ProposalCard key={p.id} proposal={p} />)}
            </div>
          </div>
        )}
      </div>

      <div className="composer">
        <div className="composer-inner">
          {preview && input.trim() && (
            <div className="share-row" aria-label="이번 질문에 공유할 데이터">
              <span className="faint">공유:</span>
              {chipCats.map((c) => {
                const blocked = privacyBlocked.includes(c);
                const on = preview.categories.includes(c);
                if (!on && !blocked && !forcedOff.has(c) && !preview.excluded_categories.includes(c) && compact) return null;
                return (
                  <button
                    key={c}
                    type="button"
                    className={`share-chip${on ? ' on' : ''}${blocked ? ' blocked' : ''}`}
                    title={blocked ? '데이터 공유 설정에서 제외된 영역' : `${CATEGORY_HINT[c]} — 클릭해 ${on ? '제외' : '포함'}`}
                    onClick={() => toggle(c)}
                    aria-pressed={on}
                  >
                    {CATEGORY_LABEL[c]}
                  </button>
                );
              })}
            </div>
          )}
          <div className="row" style={{ alignItems: 'flex-end', flexWrap: 'nowrap' }}>
            <textarea
              className="textarea"
              placeholder="무엇이든 물어보세요. 예: 지금 퇴사해도 6개월 버틸 수 있을까?"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send();
                }
              }}
              rows={compact ? 2 : 2}
              aria-label="질문 입력"
            />
            {sending ? (
              <button className="btn" onClick={() => abortRef.current?.abort()}>중지</button>
            ) : (
              <button className="btn primary" onClick={() => send()} disabled={!input.trim()}>보내기</button>
            )}
          </div>
          {!compact && <div className="faint" style={{ marginTop: 6 }}>Enter 보내기 · Shift+Enter 줄바꿈 · 계좌번호·인증정보는 전송되지 않습니다</div>}
        </div>
      </div>
    </div>
  );
}

function optionsFor(base: InspectorData, on: Set<Category>, off: Set<Category>) {
  if (on.size === 0 || !base.route) return { exclude: [...off] };
  const categories = new Set<Category>([...base.route.requested, ...on]);
  off.forEach((c) => categories.delete(c));
  return { categories: [...categories], exclude: [] as Category[] };
}

/** Proposal/memory blocks are rendered as cards, not as raw JSON. */
function stripBlocks(text: string): string {
  return text.replace(/```(proposal|memory)[\s\S]*?(```|$)/g, '').trimEnd();
}
