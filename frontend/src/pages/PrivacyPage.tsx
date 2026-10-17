import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Category } from '../api/types';
import { ALL_CATEGORIES, CATEGORY_HINT, CATEGORY_LABEL } from '../lib/labels';

export function PrivacyPage() {
  const [excluded, setExcluded] = useState<Set<Category> | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ excluded_categories: Category[] }>('/api/settings/privacy')
      .then((p) => setExcluded(new Set(p.excluded_categories)))
      .catch((e) => setError(e.message));
  }, []);

  async function toggle(c: Category) {
    if (!excluded) return;
    const next = new Set(excluded);
    if (next.has(c)) next.delete(c);
    else next.add(c);
    setExcluded(next);
    setSaved(false);
    try {
      await api('/api/settings/privacy', { method: 'PUT', body: { excluded_categories: [...next] } });
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 720 }}>
      <div className="page-head">
        <div>
          <h1>데이터 공유</h1>
          <p>꺼 둔 영역의 데이터는 어떤 질문에서도 외부 모델로 전송되지 않습니다. 질문할 때 영역별로 한 번 더 조정할 수 있습니다.</p>
        </div>
        {saved && <span className="chip ok">저장됨</span>}
      </div>
      {error && <div className="banner danger" style={{ marginBottom: 12 }}>{error}</div>}
      <div className="card">
        <ul className="list">
          {ALL_CATEGORIES.map((c) => (
            <li key={c} style={{ alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <strong>{CATEGORY_LABEL[c]}</strong>
                <div className="faint">{CATEGORY_HINT[c]}</div>
              </div>
              <label className="toggle">
                <input type="checkbox" disabled={!excluded} checked={excluded ? !excluded.has(c) : false} onChange={() => toggle(c)} />
                {excluded && (excluded.has(c) ? <span className="chip danger">전송 안 함</span> : <span className="chip ok">AI와 공유</span>)}
              </label>
            </li>
          ))}
        </ul>
      </div>
      <p className="faint" style={{ marginTop: 12 }}>계좌번호와 인증정보는 설정과 상관없이 저장·전송하지 않습니다. 대시보드처럼 이 기기 안에서만 보는 화면에는 이 설정이 적용되지 않습니다.</p>
    </div>
  );
}
