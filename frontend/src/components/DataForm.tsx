import { useState, type FormEvent } from 'react';
import type { FieldSpec } from '../api/openapi';
import { enumLabel, fieldLabel } from '../lib/resources';

type Values = Record<string, string | boolean>;

function initialValue(field: FieldSpec, current: unknown): string | boolean {
  const v = current !== undefined ? current : field.defaultValue;
  if (field.kind === 'boolean') return Boolean(v);
  if (v === null || v === undefined) return '';
  if (field.kind === 'datetime') return toLocalInput(String(v));
  return String(v);
}

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function toPayload(fields: FieldSpec[], values: Values): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.name];
    if (f.kind === 'boolean') {
      out[f.name] = Boolean(v);
      continue;
    }
    if (v === '' || v === undefined) {
      if (f.nullable) out[f.name] = null;
      continue; // let the server apply its default or report the missing field
    }
    if (f.kind === 'integer') out[f.name] = Number(v);
    else if (f.kind === 'datetime') out[f.name] = new Date(String(v)).toISOString();
    else out[f.name] = String(v).trim(); // decimals stay strings: no float rounding of money
  }
  return out;
}

interface Props {
  fields: FieldSpec[];
  current?: Record<string, unknown>;
  submitLabel: string;
  onSubmit: (payload: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}

export function DataForm({ fields, current, submitLabel, onSubmit, onCancel }: Props) {
  const [values, setValues] = useState<Values>(() =>
    Object.fromEntries(fields.map((f) => [f.name, initialValue(f, current?.[f.name])])),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(toPayload(fields, values));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const set = (name: string, v: string | boolean) => setValues((s) => ({ ...s, [name]: v }));

  return (
    <form onSubmit={submit} className="stack">
      <div className="grid grid-2">
        {fields.map((f) => (
          <div key={f.name} className="field" style={f.kind === 'longtext' ? { gridColumn: '1 / -1' } : undefined}>
            {f.kind === 'boolean' ? (
              <label className="toggle" style={{ marginTop: 18 }}>
                <input type="checkbox" checked={Boolean(values[f.name])} onChange={(e) => set(f.name, e.target.checked)} />
                {fieldLabel(f.name)}
              </label>
            ) : (
              <>
                <label htmlFor={`f-${f.name}`}>
                  {fieldLabel(f.name)} {f.required && <span className="req">*</span>}
                </label>
                {f.kind === 'enum' ? (
                  <select id={`f-${f.name}`} className="select" value={String(values[f.name])} required={f.required}
                    onChange={(e) => set(f.name, e.target.value)}>
                    {(!f.required || values[f.name] === '') && <option value="">선택</option>}
                    {f.options!.map((o) => <option key={o} value={o}>{enumLabel(o)}</option>)}
                  </select>
                ) : f.kind === 'longtext' ? (
                  <textarea id={`f-${f.name}`} className="textarea" value={String(values[f.name])}
                    onChange={(e) => set(f.name, e.target.value)} />
                ) : (
                  <input
                    id={`f-${f.name}`}
                    className="input"
                    required={f.required}
                    value={String(values[f.name])}
                    onChange={(e) => set(f.name, e.target.value)}
                    type={f.kind === 'date' ? 'date' : f.kind === 'datetime' ? 'datetime-local' : 'text'}
                    inputMode={f.kind === 'decimal' ? 'decimal' : f.kind === 'integer' ? 'numeric' : undefined}
                    pattern={f.kind === 'decimal' ? '-?[0-9]+(\\.[0-9]+)?' : f.kind === 'integer' ? '-?[0-9]+' : undefined}
                    maxLength={f.name === 'currency' || f.name === 'base' || f.name === 'quote' ? 3 : undefined}
                  />
                )}
              </>
            )}
          </div>
        ))}
      </div>
      {error && <div className="banner danger" style={{ whiteSpace: 'pre-wrap' }}>{error}</div>}
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button type="button" className="btn" onClick={onCancel}>취소</button>
        <button type="submit" className="btn primary" disabled={busy}>{submitLabel}</button>
      </div>
    </form>
  );
}
