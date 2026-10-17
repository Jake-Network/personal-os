import { useState } from 'react';
import { api } from '../api/client';
import type { Category, InspectorData, SnapshotCompare } from '../api/types';
import { ALL_CATEGORIES, CATEGORY_LABEL, ROUTE_REASON, TABLE_LABEL, TOOL_LABEL, flagDetail, flagText } from '../lib/labels';
import { dateTime, relative } from '../lib/format';

interface Props {
  data: InspectorData | null;
  mode: 'preview' | 'answer' | 'snapshot';
  loading?: boolean;
  className?: string;
  onClose?: () => void;
}

const TITLE = {
  preview: '보낼 데이터 미리보기',
  answer: '이번 답변이 참조한 데이터',
  snapshot: '선택한 답변의 근거 데이터',
};

/** [참조 중인 데이터] panel (PRD §4.2). */
export function ContextInspector({ data, mode, loading, className = '', onClose }: Props) {
  const [compare, setCompare] = useState<SnapshotCompare | null>(null);
  const [comparing, setComparing] = useState(false);

  const used = new Set(data?.categories ?? []);
  const excluded = new Set(data?.excluded_categories ?? []);
  const refsByTool = groupBy((data?.record_references ?? []).filter((r) => r.tool), (r) => r.tool);
  const flags = (data?.data_quality_flags ?? []).filter((f) => f.code !== 'category_excluded_by_user');

  async function runCompare() {
    if (!data?.context_snapshot_id) return;
    setComparing(true);
    try {
      setCompare(await api<SnapshotCompare>(`/api/advisor/snapshots/${data.context_snapshot_id}/compare`));
    } finally {
      setComparing(false);
    }
  }

  return (
    <aside className={`inspector ${className}`} aria-label="참조 중인 데이터">
      <section className="row">
        <h2 style={{ margin: 0 }}>참조 중인 데이터</h2>
        <span className="spacer" />
        {onClose && <button className="btn sm ghost" onClick={onClose}>닫기</button>}
      </section>
      {!data ? (
        <section className="faint">
          {loading ? '불러오는 중…' : '질문을 입력하면 어떤 개인 데이터가 AI로 전송되는지 여기에서 먼저 확인할 수 있습니다.'}
        </section>
      ) : (
        <>
          <section>
            <h3>{TITLE[mode]}</h3>
            {data.route && <div className="faint" style={{ marginBottom: 8 }}>{ROUTE_REASON[data.route.reason]}
              {data.route.matched_terms.length > 0 && ` · ${data.route.matched_terms.slice(0, 4).join(', ')}`}</div>}
            {ALL_CATEGORIES.map((c: Category) => {
              const state = used.has(c) ? 'on' : excluded.has(c) ? 'off' : '';
              return (
                <div className="cat-row" key={c}>
                  <span className={`dot ${state}`} />
                  <span style={{ flex: 1, color: state ? undefined : 'var(--text-3)' }}>{CATEGORY_LABEL[c]}</span>
                  {state === 'on' && <span className="faint">{relative(data.source_updated_at[c])}</span>}
                  {state === 'off' && <span className="chip danger">공유 제외</span>}
                  {!state && <span className="faint">사용 안 함</span>}
                </div>
              );
            })}
          </section>

          {flags.length > 0 && (
            <section>
              <h3>데이터 품질 · 한계</h3>
              <div className="stack" style={{ gap: 6 }}>
                {flags.map((f, n) => (
                  <div key={n} className="small">
                    <span className="chip warn">{CATEGORY_LABEL[f.category as Category] ?? f.category}</span>{' '}
                    {flagText(f.code)}
                    {flagDetail(f.code, f.detail) && <div className="faint">{flagDetail(f.code, f.detail)}</div>}
                  </div>
                ))}
              </div>
            </section>
          )}

          <section>
            <h3>조회한 레코드</h3>
            {Object.keys(refsByTool).length === 0 && <div className="faint">조회된 레코드가 없습니다.</div>}
            {Object.entries(refsByTool).map(([tool, refs]) => (
              <div key={tool} style={{ marginBottom: 10 }}>
                <div className="small" style={{ fontWeight: 600 }}>{TOOL_LABEL[tool] ?? tool}</div>
                <div className="row" style={{ gap: 4, marginTop: 4 }}>
                  {refs.map((r, n) =>
                    r.count !== undefined ? (
                      <span key={n} className="chip">{TABLE_LABEL[r.table ?? ''] ?? r.table} {r.count}건</span>
                    ) : (
                      <span key={n} className="chip ref" title={r.updated_at ? `수정 ${dateTime(r.updated_at)}` : undefined}>
                        {TABLE_LABEL[r.table ?? ''] ?? r.table} #{r.id}
                      </span>
                    ),
                  )}
                </div>
              </div>
            ))}
          </section>

          {mode !== 'preview' && data.context_snapshot_id && (
            <section>
              <h3>Context Snapshot</h3>
              <div className="faint mono" style={{ wordBreak: 'break-all' }}>{data.context_snapshot_id}</div>
              {data.context_reused && <div className="faint">직전 질문과 데이터가 같아 기존 스냅샷을 재사용했습니다.</div>}
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn sm" onClick={runCompare} disabled={comparing}>현재 데이터와 비교</button>
              </div>
              {compare && (
                <div className="small" style={{ marginTop: 8 }}>
                  {compare.changed_sections.length === 0 ? (
                    <span className="chip ok">상담 이후 변경 없음</span>
                  ) : (
                    <>
                      <div>상담 이후 바뀐 데이터:</div>
                      <div className="row" style={{ gap: 4, marginTop: 4 }}>
                        {compare.changed_sections.map((s) => <span key={s} className="chip warn">{TOOL_LABEL[s] ?? s}</span>)}
                      </div>
                      <div className="faint" style={{ marginTop: 4 }}>
                        답변은 {dateTime(compare.snapshot_generated_at)} 기준 데이터로 작성되었습니다.
                      </div>
                    </>
                  )}
                </div>
              )}
            </section>
          )}
        </>
      )}
    </aside>
  );
}

function groupBy<T>(items: T[], key: (t: T) => string): Record<string, T[]> {
  return items.reduce<Record<string, T[]>>((acc, item) => {
    (acc[key(item)] ??= []).push(item);
    return acc;
  }, {});
}
