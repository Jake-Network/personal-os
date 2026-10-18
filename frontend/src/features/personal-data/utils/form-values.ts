import type { FieldSpec } from './schema-fields';

export type FormValues = Record<string, string | boolean>;

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function initialValues(fields: FieldSpec[], current?: Record<string, unknown>): FormValues {
  return Object.fromEntries(
    fields.map(f => {
      const v = current?.[f.name] !== undefined ? current[f.name] : f.defaultValue;
      if (f.kind === 'boolean') return [f.name, Boolean(v)];
      if (v === null || v === undefined) return [f.name, ''];
      if (f.kind === 'datetime') return [f.name, toLocalInput(String(v))];
      return [f.name, String(v)];
    }),
  );
}

export function toPayload(fields: FieldSpec[], values: FormValues): Record<string, unknown> {
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
    if (f.kind === 'integer' && f.name !== 'quantity') out[f.name] = Number(v);
    else if (f.kind === 'datetime') out[f.name] = new Date(String(v)).toISOString();
    else out[f.name] = String(v).trim(); // decimals stay strings: no float rounding of money
  }
  return out;
}
