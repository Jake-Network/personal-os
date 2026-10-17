import { useState } from 'react';
import { api } from '../api/client';
import type { Memory, Proposal } from '../api/types';
import { ACTION_LABEL, MEMORY_KIND_LABEL } from '../lib/labels';
import { enumLabel, fieldLabel } from '../lib/resources';

type Decision = 'approved' | 'rejected' | 'error';

export function ProposalCard({ proposal, onDone }: { proposal: Proposal; onDone?: () => void }) {
  const [state, setState] = useState<Decision | null>(
    proposal.status && proposal.status !== 'pending' ? (proposal.status as Decision) : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function decide(kind: 'approve' | 'reject') {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/proposals/${proposal.id}/${kind}`, { method: 'POST' });
      setState(kind === 'approve' ? 'approved' : 'rejected');
      onDone?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="proposal">
      <div className="row">
        <span className="chip accent">제안 · {ACTION_LABEL[proposal.action] ?? proposal.action}</span>
        <span className="spacer" />
        {state === 'approved' && <span className="chip ok">승인되어 반영됨</span>}
        {state === 'rejected' && <span className="chip">거절됨</span>}
      </div>
      <dl className="small" style={{ margin: '8px 0', display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 12px' }}>
        {Object.entries(proposal.payload).map(([k, v]) => (
          <div key={k} style={{ display: 'contents' }}>
            <dt className="muted">{fieldLabel(k)}</dt>
            <dd style={{ margin: 0 }}>{enumLabel(v)}</dd>
          </div>
        ))}
      </dl>
      {proposal.rationale && <div className="faint" style={{ marginBottom: 8 }}>{proposal.rationale}</div>}
      {error && <div className="banner danger" style={{ marginBottom: 8 }}>{error}</div>}
      {!state && (
        <div className="row">
          <button className="btn sm primary" disabled={busy} onClick={() => decide('approve')}>승인하고 반영</button>
          <button className="btn sm" disabled={busy} onClick={() => decide('reject')}>거절</button>
          <span className="faint">승인 전에는 아무것도 변경되지 않습니다.</span>
        </div>
      )}
    </div>
  );
}

export function MemoryProposalCard({ memory, onDone }: { memory: Pick<Memory, 'id' | 'kind' | 'content'> & { status?: string }; onDone?: () => void }) {
  const [state, setState] = useState<string | null>(memory.status && memory.status !== 'proposed' ? memory.status : null);
  const [busy, setBusy] = useState(false);

  async function decide(kind: 'confirm' | 'reject') {
    setBusy(true);
    try {
      await api(`/api/memories/${memory.id}/${kind}`, { method: 'POST' });
      setState(kind === 'confirm' ? 'confirmed' : 'rejected');
      onDone?.();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="proposal">
      <div className="row">
        <span className="chip accent">기억 제안 · {MEMORY_KIND_LABEL[memory.kind] ?? memory.kind}</span>
        <span className="spacer" />
        {state === 'confirmed' && <span className="chip ok">저장됨</span>}
        {state === 'rejected' && <span className="chip">저장 안 함</span>}
      </div>
      <div style={{ margin: '8px 0' }}>{memory.content}</div>
      {!state && (
        <div className="row">
          <button className="btn sm primary" disabled={busy} onClick={() => decide('confirm')}>장기 기억에 저장</button>
          <button className="btn sm" disabled={busy} onClick={() => decide('reject')}>저장 안 함</button>
        </div>
      )}
    </div>
  );
}
