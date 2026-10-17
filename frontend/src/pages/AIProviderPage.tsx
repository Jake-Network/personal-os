import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { ProviderStatus, UsageEvent } from '../api/types';
import { dateTime } from '../lib/format';
import { useAsync } from '../lib/useAsync';

const PROVIDERS = [
  { key: 'chatgpt_plan', label: 'ChatGPT 구독 (기본)', note: 'ChatGPT 요금제 사용량으로 응답합니다. 별도 API 과금이 없습니다.' },
  { key: 'openai_api_key', label: 'OpenAI API Key', note: '서버 환경변수 OPENAI_API_KEY로 API 계정에 과금됩니다. 직접 선택할 때만 사용됩니다.' },
  { key: 'codex_app_server', label: 'Codex app-server', note: '아직 지원하지 않습니다.' },
];

const OUTCOME: Record<string, string> = {
  completed: '완료', incomplete: '미완료', failed: '실패', quota_exceeded: '한도 초과', auth_error: '인증 오류',
};

const CALLBACK_ERROR: Record<string, string> = {
  access_denied: 'ChatGPT 로그인 동의가 취소되었습니다.',
  invalid_grant: '인증 코드가 만료되었습니다. 다시 시도하세요.',
};

export function AIProviderPage() {
  const [params, setParams] = useSearchParams();
  const status = useAsync(() => api<ProviderStatus>('/api/settings/ai-provider'), []);
  const usage = useAsync(() => api<UsageEvent[]>('/api/settings/ai-provider/usage-events?limit=20'), []);
  const [models, setModels] = useState<string[] | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'danger' | 'warn'; text: string } | null>(null);

  // Result flags from the OAuth callback redirect (never tokens).
  useEffect(() => {
    const result = params.get('chatgpt');
    if (!result) return;
    if (result === 'connected') {
      setNotice(params.get('plan_usage') === 'enabled'
        ? { tone: 'ok', text: 'ChatGPT 계정이 연결되었습니다.' }
        : { tone: 'warn', text: 'ChatGPT 로그인은 되었지만 구독 사용 권한이 승인되지 않았습니다. 권한을 포함해 다시 연결하세요.' });
    } else {
      const code = params.get('code') ?? '';
      setNotice({ tone: 'danger', text: CALLBACK_ERROR[code] ?? `연결에 실패했습니다 (${code || '알 수 없는 오류'}).` });
    }
    setParams({}, { replace: true });
  }, [params, setParams]);

  const s = status.data;
  const usable = s?.connected && s.plan_usage_enabled;

  useEffect(() => {
    if (!s) return;
    if (s.provider === 'chatgpt_plan' && !usable) {
      setModels(null);
      return;
    }
    api<string[]>('/api/settings/ai-provider/models')
      .then((m) => { setModels(m); setModelError(null); })
      .catch((e) => setModelError(e.message));
  }, [s, usable]);

  async function login(forceConsent = false) {
    setBusy(true);
    try {
      const { authorize_url } = await api<{ authorize_url: string }>(
        `/api/settings/ai-provider/chatgpt/login${forceConsent ? '?force_consent=true' : ''}`, { method: 'POST' });
      window.location.href = authorize_url;
    } catch (e) {
      setNotice({ tone: 'danger', text: (e as Error).message });
      setBusy(false);
    }
  }

  async function disconnect() {
    if (!confirm('ChatGPT 연결을 해제할까요? 저장된 토큰이 삭제되고 철회됩니다.')) return;
    await api('/api/settings/ai-provider/chatgpt', { method: 'DELETE' });
    await status.reload();
  }

  async function select(provider: string, model: string | null) {
    await api('/api/settings/ai-provider/selection', { method: 'PUT', body: { provider, model } });
    await status.reload();
  }

  return (
    <div className="page" style={{ maxWidth: 860 }}>
      <div className="page-head">
        <div>
          <h1>AI Provider</h1>
          <p>ChatGPT 로그인은 모델 사용을 위한 인증 수단입니다. ChatGPT의 대화나 메모리는 읽지 않습니다.</p>
        </div>
      </div>

      {notice && <div className={`banner ${notice.tone}`} style={{ marginBottom: 14 }}>{notice.text}</div>}
      {status.error && <div className="banner danger" style={{ marginBottom: 14 }}>{status.error.message}</div>}

      <section className="card" style={{ marginBottom: 14 }}>
        <div className="card-head">
          <h2>ChatGPT 계정</h2>
          {s && (s.connected ? (usable ? <span className="chip ok">연결됨 · 구독 사용 가능</span> : <span className="chip warn">구독 사용 권한 없음</span>)
            : s.status === 'needs_reauth' ? <span className="chip danger">재인증 필요</span> : <span className="chip">연결 안 됨</span>)}
        </div>
        <div className="card-pad stack">
          {!s ? <div className="faint">불러오는 중…</div> : s.connected || s.status === 'needs_reauth' ? (
            <>
              <div className="grid grid-2">
                <Info label="계정" value={s.display_name ? `${s.display_name} (${s.email ?? ''})` : (s.email ?? '—')} />
                <Info label="토큰 만료" value={s.access_expires_at ? `${dateTime(s.access_expires_at)} (자동 갱신)` : '—'} />
                <Info label="승인된 권한" value={s.scopes.join(' ') || '—'} mono />
                <Info label="최근 오류" value={s.last_error_code ?? '없음'} mono />
              </div>
              {s.status === 'needs_reauth' && <div className="banner danger">인증이 만료되었거나 철회되었습니다. 다시 로그인하세요.</div>}
              {s.connected && !s.plan_usage_enabled && (
                <div className="banner warn">구독 사용 권한(chatgpt.tokens.use.direct)이 없어 상담을 할 수 없습니다. 유료 API로 자동 전환하지 않습니다.</div>
              )}
              <div className="row">
                <button className="btn" disabled={busy} onClick={() => login(!s.plan_usage_enabled)}>
                  {s.plan_usage_enabled ? '재인증' : '권한 포함해 다시 연결'}
                </button>
                <a className="btn" href={s.usage_url} target="_blank" rel="noreferrer">사용량 확인 ↗</a>
                <span className="spacer" />
                <button className="btn danger" onClick={disconnect}>연결 해제</button>
              </div>
            </>
          ) : (
            <>
              <div className="muted">ChatGPT Plus/Pro 구독 사용량으로 AI 상담을 이용합니다. 토큰은 서버에만 암호화해 저장되고 브라우저에는 노출되지 않습니다.</div>
              <div><button className="btn primary" disabled={busy} onClick={() => login()}>Continue with ChatGPT</button></div>
            </>
          )}
        </div>
      </section>

      <section className="card" style={{ marginBottom: 14 }}>
        <div className="card-head"><h2>Inference Provider · 모델</h2></div>
        <div className="card-pad stack">
          {PROVIDERS.map((p) => (
            <label key={p.key} className="toggle" style={{ alignItems: 'flex-start' }}>
              <input type="radio" name="provider" checked={s?.provider === p.key} disabled={p.key === 'codex_app_server'}
                onChange={() => {
                  if (p.key === 'openai_api_key' && !confirm('API Key provider는 OpenAI API 계정에 과금됩니다. 전환할까요?')) return;
                  void select(p.key, null);
                }} />
              <span><strong>{p.label}</strong><div className="faint">{p.note}</div></span>
            </label>
          ))}
          <div className="field" style={{ maxWidth: 360 }}>
            <label htmlFor="model">모델</label>
            <select id="model" className="select" value={s?.model ?? ''} disabled={!models}
              onChange={(e) => s && select(s.provider, e.target.value || null)}>
              <option value="">자동 (계정의 첫 번째 모델)</option>
              {models?.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            {!models && !modelError && <span className="faint">계정을 연결하면 사용 가능한 모델 목록이 표시됩니다.</span>}
            {modelError && <span className="faint" style={{ color: 'var(--danger)' }}>{modelError}</span>}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head"><h2>최근 모델 호출</h2><span className="faint">토큰 원문은 기록하지 않습니다</span></div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>시각</th><th>Provider</th><th>모델</th><th>결과</th><th className="num">입력/출력 토큰</th><th className="num">지연</th></tr></thead>
            <tbody>
              {usage.data?.map((u) => (
                <tr key={u.id}>
                  <td>{dateTime(u.created_at)}</td><td>{u.provider}</td><td>{u.model ?? '—'}</td>
                  <td><span className={`chip ${u.outcome === 'completed' ? 'ok' : u.outcome === 'quota_exceeded' ? 'warn' : 'danger'}`}>{OUTCOME[u.outcome] ?? u.outcome}</span>
                    {u.error_code && <span className="faint mono"> {u.error_code}</span>}</td>
                  <td className="num">{u.input_tokens ?? '—'} / {u.output_tokens ?? '—'}</td>
                  <td className="num">{u.latency_ms != null ? `${(u.latency_ms / 1000).toFixed(1)}s` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {usage.data?.length === 0 && <div className="empty">호출 기록이 없습니다.</div>}
      </section>
    </div>
  );
}

function Info({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="faint">{label}</div>
      <div className={mono ? 'mono' : undefined} style={{ wordBreak: 'break-all' }}>{value}</div>
    </div>
  );
}
