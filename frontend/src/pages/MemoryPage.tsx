import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { Decision, Memory } from '../api/types';
import { dateOnly } from '../lib/format';
import { MEMORY_KIND_LABEL } from '../lib/labels';
import { useAsync } from '../lib/useAsync';

export function MemoryPage() {
  const [tab, setTab] = useState<'memory' | 'journal'>('memory');
  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <div className="page-head">
        <div>
          <h1>기억 · 의사결정</h1>
          <p>확인된 기억만 AI 상담의 개인 프로필로 사용됩니다. 의사결정은 나중에 실제 결과와 비교할 수 있습니다.</p>
        </div>
        <div className="row">
          <button className={`btn${tab === 'memory' ? ' primary' : ''}`} onClick={() => setTab('memory')}>장기 기억</button>
          <button className={`btn${tab === 'journal' ? ' primary' : ''}`} onClick={() => setTab('journal')}>Decision Journal</button>
        </div>
      </div>
      {tab === 'memory' ? <Memories /> : <Journal />}
    </div>
  );
}

function Memories() {
  const list = useAsync(() => api<Memory[]>('/api/memories?status=confirmed'), []);
  const [kind, setKind] = useState<Memory['kind']>('preference');
  const [content, setContent] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      await api('/api/memories', { body: { kind, content } });
      setContent('');
      setError(null);
      await list.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove(id: number) {
    if (!confirm('이 기억을 삭제할까요?')) return;
    await api(`/api/memories/${id}`, { method: 'DELETE' });
    await list.reload();
  }

  return (
    <div className="stack" style={{ gap: 14 }}>
      <form className="card card-pad row" onSubmit={add} style={{ flexWrap: 'nowrap', alignItems: 'flex-end' }}>
        <div className="field" style={{ width: 130, flex: 'none' }}>
          <label htmlFor="m-kind">종류</label>
          <select id="m-kind" className="select" value={kind} onChange={(e) => setKind(e.target.value as Memory['kind'])}>
            {Object.entries(MEMORY_KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div className="field" style={{ flex: 1 }}>
          <label htmlFor="m-content">내용</label>
          <input id="m-content" className="input" value={content} onChange={(e) => setContent(e.target.value)}
            placeholder="예: 연봉보다 성장 기회를 우선한다" required />
        </div>
        <button className="btn primary" type="submit">저장</button>
      </form>
      {error && <div className="banner danger">{error}</div>}
      <div className="card">
        <ul className="list">
          {list.data?.map((m) => (
            <li key={m.id}>
              <span className="chip accent">{MEMORY_KIND_LABEL[m.kind]}</span>
              <span style={{ flex: 1 }}>{m.content}</span>
              <span className="faint">{m.source === 'advisor' ? 'AI 제안 → 확인' : '직접 입력'}</span>
              <button className="btn sm ghost danger" onClick={() => remove(m.id)}>삭제</button>
            </li>
          ))}
        </ul>
        {list.data?.length === 0 && <div className="empty">저장된 기억이 없습니다.</div>}
      </div>
    </div>
  );
}

function Journal() {
  const list = useAsync(() => api<Decision[]>('/api/decisions'), []);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ title: '', choice: '', rationale: '', alternatives: '', expected_outcome: '', review_on: '' });
  const [reviewing, setReviewing] = useState<number | null>(null);
  const [outcome, setOutcome] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api('/api/decisions', {
        body: {
          title: form.title,
          choice: form.choice,
          rationale: form.rationale,
          alternatives: form.alternatives.split('\n').map((s) => s.trim()).filter(Boolean),
          expected_outcome: form.expected_outcome || null,
          review_on: form.review_on ? new Date(`${form.review_on}T09:00:00`).toISOString() : null,
        },
      });
      setForm({ title: '', choice: '', rationale: '', alternatives: '', expected_outcome: '', review_on: '' });
      setOpen(false);
      setError(null);
      await list.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function review(id: number) {
    await api(`/api/decisions/${id}/review`, { body: { actual_outcome: outcome } });
    setReviewing(null);
    setOutcome('');
    await list.reload();
  }

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="row"><span className="spacer" /><button className="btn primary" onClick={() => setOpen((v) => !v)}>결정 기록하기</button></div>
      {open && (
        <form className="card card-pad stack" onSubmit={create}>
          <div className="field"><label>결정 *</label><input className="input" required value={form.title} onChange={set('title')} placeholder="예: A사 오퍼 수락 여부" /></div>
          <div className="grid grid-2">
            <div className="field"><label>선택한 안 *</label><input className="input" required value={form.choice} onChange={set('choice')} /></div>
            <div className="field"><label>회고 예정일</label><input className="input" type="date" value={form.review_on} onChange={set('review_on')} /></div>
          </div>
          <div className="field"><label>고려한 대안 (줄마다 하나)</label><textarea className="textarea" value={form.alternatives} onChange={set('alternatives')} /></div>
          <div className="field"><label>선택 이유 *</label><textarea className="textarea" required value={form.rationale} onChange={set('rationale')} /></div>
          <div className="field"><label>예상 결과</label><textarea className="textarea" value={form.expected_outcome} onChange={set('expected_outcome')} /></div>
          {error && <div className="banner danger">{error}</div>}
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <button type="button" className="btn" onClick={() => setOpen(false)}>취소</button>
            <button type="submit" className="btn primary">기록</button>
          </div>
        </form>
      )}
      {list.data?.length === 0 && <div className="card empty">기록된 의사결정이 없습니다.</div>}
      {list.data?.map((d) => (
        <article key={d.id} className="card card-pad stack" style={{ gap: 6 }}>
          <div className="row">
            <h2 style={{ flex: 1 }}>{d.title}</h2>
            <span className="faint">{dateOnly(d.decided_at)}</span>
            {d.reviewed_at ? <span className="chip ok">회고 완료</span>
              : d.review_on && new Date(d.review_on) < new Date() ? <span className="chip warn">회고 시점 지남</span> : null}
          </div>
          <div><span className="muted">선택:</span> {d.choice}</div>
          {d.alternatives.length > 0 && <div className="small"><span className="muted">대안:</span> {d.alternatives.join(' · ')}</div>}
          <div className="small"><span className="muted">이유:</span> {d.rationale}</div>
          <div className="grid grid-2" style={{ marginTop: 6 }}>
            <div className="card-pad" style={{ background: 'var(--surface-2)', borderRadius: 6 }}>
              <div className="faint">예상 결과</div>{d.expected_outcome ?? '—'}
            </div>
            <div className="card-pad" style={{ background: 'var(--surface-2)', borderRadius: 6 }}>
              <div className="faint">실제 결과</div>
              {d.actual_outcome ?? (reviewing === d.id ? (
                <div className="stack" style={{ marginTop: 4 }}>
                  <textarea className="textarea" value={outcome} onChange={(e) => setOutcome(e.target.value)} />
                  <div className="row"><button className="btn sm primary" disabled={!outcome.trim()} onClick={() => review(d.id)}>저장</button>
                    <button className="btn sm" onClick={() => setReviewing(null)}>취소</button></div>
                </div>
              ) : <button className="btn sm" style={{ marginTop: 4 }} onClick={() => setReviewing(d.id)}>결과 기록</button>)}
            </div>
          </div>
          {d.conversation_id && <Link to={`/advisor/${d.conversation_id}`} className="small">관련 상담 보기</Link>}
        </article>
      ))}
    </div>
  );
}
