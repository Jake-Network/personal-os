import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { Memory, Proposal } from '../api/types';
import { MemoryProposalCard, ProposalCard } from '../components/ProposalCard';
import { dateTime } from '../lib/format';
import { useAsync } from '../lib/useAsync';

export function ApprovalsPage() {
  const proposals = useAsync(() => api<Proposal[]>('/api/proposals?status=pending'), []);
  const memories = useAsync(() => api<Memory[]>('/api/memories?status=proposed'), []);
  const history = useAsync(
    async () => [...(await api<Proposal[]>('/api/proposals?status=approved')), ...(await api<Proposal[]>('/api/proposals?status=rejected'))]
      .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '')),
    [],
  );

  const refresh = () => {
    void proposals.reload();
    void memories.reload();
    void history.reload();
  };
  const empty = proposals.data?.length === 0 && memories.data?.length === 0;

  return (
    <div className="page" style={{ maxWidth: 820 }}>
      <div className="page-head">
        <div>
          <h1>승인 대기</h1>
          <p>AI가 제안한 변경과 장기 기억입니다. 승인하기 전에는 아무것도 반영되지 않습니다.</p>
        </div>
      </div>
      {empty && <div className="card empty">승인할 항목이 없습니다.</div>}
      <div className="stack">
        {proposals.data?.map((p) => (
          <div key={p.id}>
            <div className="faint" style={{ marginBottom: 4 }}>
              {dateTime(p.created_at)} {p.conversation_id && <Link to={`/advisor/${p.conversation_id}`}>· 상담 보기</Link>}
            </div>
            <ProposalCard proposal={p} onDone={refresh} />
          </div>
        ))}
        {memories.data?.map((m) => <MemoryProposalCard key={m.id} memory={m} onDone={refresh} />)}
      </div>

      {(history.data?.length ?? 0) > 0 && (
        <>
          <h2 style={{ margin: '28px 0 10px' }}>처리 내역</h2>
          <div className="stack">
            {history.data!.slice(0, 20).map((p) => <ProposalCard key={p.id} proposal={p} />)}
          </div>
        </>
      )}
    </div>
  );
}
