import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { Conversation, InspectorData } from '../api/types';
import { AdvisorChat, type InspectorMode } from '../components/AdvisorChat';
import { ContextInspector } from '../components/ContextInspector';
import { relative } from '../lib/format';

const DOMAINS: { key: string; label: string }[] = [
  { key: 'financial', label: '재무' },
  { key: 'investment', label: '투자' },
  { key: 'career', label: '커리어' },
  { key: 'calendar', label: '일정' },
  { key: 'health', label: '건강' },
];

export function AdvisorPage() {
  const params = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const conversationId = params.id ? Number(params.id) : null;
  const newDomain = search.get('domain');

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [query, setQuery] = useState('');
  const [inspector, setInspector] = useState<{ data: InspectorData | null; mode: InspectorMode; loading?: boolean }>({
    data: null,
    mode: 'preview',
  });
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);

  const loadConversations = useCallback(() => {
    const q = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : '';
    api<Conversation[]>(`/api/advisor/conversations${q}`).then(setConversations).catch(() => {});
  }, [query]);

  useEffect(() => {
    const t = setTimeout(loadConversations, 200);
    return () => clearTimeout(t);
  }, [loadConversations]);

  useEffect(() => {
    setInspector({ data: null, mode: 'preview' });
    setListOpen(false);
  }, [conversationId, newDomain]);

  const current = conversations.find((c) => c.id === conversationId);
  const domain = current?.domain ?? newDomain;

  async function remove() {
    if (!conversationId || !confirm('이 상담과 상담에 사용된 Context Snapshot을 삭제할까요?')) return;
    await api(`/api/advisor/conversations/${conversationId}`, { method: 'DELETE' });
    navigate('/advisor');
    loadConversations();
  }

  return (
    <div className="page wide">
      <div className="advisor">
        <aside className={`conv-list${listOpen ? ' open' : ''}`}>
          <div className="stack" style={{ padding: 12, borderBottom: '1px solid var(--border)' }}>
            <Link to="/advisor" className="btn primary" style={{ justifyContent: 'center' }}>새 상담</Link>
            <div className="row" style={{ gap: 4 }}>
              {DOMAINS.map((d) => (
                <Link key={d.key} to={`/advisor?domain=${d.key}`} className="chip" title={`${d.label} 상담 시작`}>{d.label}</Link>
              ))}
            </div>
            <input className="input" placeholder="상담 검색" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="conv-scroll">
            {conversations.length === 0 && <div className="empty">상담 기록이 없습니다</div>}
            {conversations.map((c) => (
              <Link key={c.id} to={`/advisor/${c.id}`} className={`conv-item${c.id === conversationId ? ' active' : ''}`}>
                <div className="t">{c.title}</div>
                <div className="faint">{relative(c.updated_at)}{c.domain && ` · ${DOMAINS.find((d) => d.key === c.domain)?.label}`}</div>
              </Link>
            ))}
          </div>
        </aside>

        <AdvisorChat
          conversationId={conversationId}
          domain={domain}
          onConversationCreated={(id) => {
            navigate(`/advisor/${id}`, { replace: true });
            loadConversations();
          }}
          onInspector={(data, mode, loading) => {
            setInspector({ data, mode, loading });
            if (mode === 'snapshot') setInspectorOpen(true);
          }}
          header={
            <div className="chat-head">
              <h2 style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {current?.title ?? (domain ? `새 ${DOMAINS.find((d) => d.key === domain)?.label ?? ''} 상담` : '새 상담')}
              </h2>
              <button className="btn sm mobile-only" onClick={() => setListOpen((v) => !v)}>상담 목록</button>
              <button className="btn sm" onClick={() => setInspectorOpen((v) => !v)}>참조 데이터</button>
              {conversationId && <button className="btn sm danger" onClick={remove}>삭제</button>}
            </div>
          }
        />

        <ContextInspector
          data={inspector.data}
          mode={inspector.mode}
          loading={inspector.loading}
          className={inspectorOpen ? 'force' : ''}
          onClose={inspectorOpen ? () => setInspectorOpen(false) : undefined}
        />
      </div>
    </div>
  );
}
