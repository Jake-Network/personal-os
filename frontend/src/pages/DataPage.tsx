import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';
import { createSchemaFields, type FieldSpec } from '../api/openapi';
import { DataForm } from '../components/DataForm';
import { dateOnly, dateTime, money, plain } from '../lib/format';
import { RESOURCES, enumLabel, fieldLabel } from '../lib/resources';
import { useAsync } from '../lib/useAsync';

type Row = Record<string, any> & { id: number };

const MONEY_FIELDS = new Set(['balance', 'value', 'amount', 'monthly_payment', 'avg_cost', 'last_price']);

function cell(row: Row, col: string, field?: FieldSpec): string {
  const v = row[col];
  if (v === null || v === undefined || v === '') return '—';
  if (MONEY_FIELDS.has(col)) return money(v, row.currency ?? 'KRW');
  if (field?.kind === 'enum') return enumLabel(v);
  if (field?.kind === 'date') return dateOnly(v);
  if (field?.kind === 'datetime') return dateTime(v);
  return plain(v);
}

export function DataPage() {
  const { resource = '' } = useParams();
  const meta = RESOURCES.find((r) => r.name === resource);
  const [fields, setFields] = useState<FieldSpec[] | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Row | 'new' | null>(null);
  const rows = useAsync(() => api<Row[]>(`/api/data/${resource}`), [resource]);

  useEffect(() => {
    setFields(null);
    setEditing(null);
    createSchemaFields(resource).then(setFields).catch((e) => setSchemaError(e.message));
  }, [resource]);

  if (!meta) return <div className="page"><div className="empty">알 수 없는 데이터 종류입니다.</div></div>;
  const fieldMap = Object.fromEntries((fields ?? []).map((f) => [f.name, f]));
  const numeric = (c: string) => MONEY_FIELDS.has(c) || ['quantity', 'rate', 'weight', 'interest_rate', 'duration_minutes', 'estimate_minutes', 'current_value', 'target_value'].includes(c);

  async function save(payload: Record<string, unknown>) {
    if (editing === 'new') await api(`/api/data/${resource}`, { body: payload });
    else if (editing) await api(`/api/data/${resource}/${editing.id}`, { method: 'PUT', body: payload });
    setEditing(null);
    await rows.reload();
  }

  async function remove(row: Row) {
    if (!confirm(`이 ${meta!.label} 항목을 삭제할까요?`)) return;
    await api(`/api/data/${resource}/${row.id}`, { method: 'DELETE' });
    await rows.reload();
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="faint">{meta.group}</div>
          <h1>{meta.label}</h1>
          <p>
            {meta.financial
              ? '직접 입력한 값만 사용합니다. AI는 이 데이터를 변경할 수 없고, 모든 변경은 감사로그에 남습니다.'
              : 'AI 상담이 이 데이터를 조회해 답변합니다.'}
          </p>
        </div>
        <button className="btn primary" disabled={!fields} onClick={() => setEditing('new')}>추가</button>
      </div>

      {(schemaError || rows.error) && <div className="banner danger" style={{ marginBottom: 12 }}>{schemaError ?? rows.error?.message}</div>}

      <div className="card">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                {meta.columns.map((c) => <th key={c} className={numeric(c) ? 'num' : undefined}>{fieldLabel(c)}</th>)}
                <th />
              </tr>
            </thead>
            <tbody>
              {(rows.data ?? []).map((row) => (
                <tr key={row.id}>
                  {meta.columns.map((c) => <td key={c} className={numeric(c) ? 'num' : undefined}>{cell(row, c, fieldMap[c])}</td>)}
                  <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                    <button className="btn sm ghost" onClick={() => setEditing(row)}>수정</button>
                    <button className="btn sm ghost danger" onClick={() => remove(row)}>삭제</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.data?.length === 0 && <div className="empty">아직 등록된 {meta.label}이(가) 없습니다.</div>}
        {rows.loading && !rows.data && <div className="empty">불러오는 중…</div>}
      </div>

      {editing && fields && (
        <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && setEditing(null)}>
          <div className="modal card card-pad" role="dialog" aria-label={`${meta.label} ${editing === 'new' ? '추가' : '수정'}`}>
            <h2 style={{ marginBottom: 14 }}>{meta.label} {editing === 'new' ? '추가' : '수정'}</h2>
            <DataForm
              fields={fields}
              current={editing === 'new' ? undefined : editing}
              submitLabel={editing === 'new' ? '추가' : '저장'}
              onSubmit={save}
              onCancel={() => setEditing(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
