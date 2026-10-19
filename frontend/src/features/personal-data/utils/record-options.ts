import { TRANSACTION_KIND_LABEL } from '@/features/finance/transaction-kinds';
import { dateOnly } from '@/lib/utils/format';

export type RecordOption = { value: string; label: string };

// Labels are presentation only. The option value always retains the server record ID; IDs are not shown,
// so records with the same label are told apart by their order instead.
export function recordOptions(rows: Array<Record<string, unknown> & { id: number }>): RecordOption[] {
  const labelled = rows.map(row => {
    const title = row.company
      ? [...new Set([row.company, row.title, row.role].filter(Boolean))].join(' · ')
      : (row.name ??
        row.title ??
        row.content ??
        row.symbol ??
        [
          row.occurred_on || row.occurred_at ? dateOnly(String(row.occurred_on ?? row.occurred_at)) : null,
          row.kind ? (TRANSACTION_KIND_LABEL[String(row.kind)] ?? row.kind) : null,
          row.amount != null ? [row.amount, row.currency].filter(v => v != null && v !== '').join(' ') : null,
          row.description ?? row.note,
          row.category,
        ]
          .filter(Boolean)
          .join(' · '));
    return { value: String(row.id), label: String(title || '이름 없는 기록') };
  });
  const total = new Map<string, number>();
  for (const o of labelled) total.set(o.label, (total.get(o.label) ?? 0) + 1);
  const seen = new Map<string, number>();
  return labelled.map(o => {
    if (total.get(o.label)! < 2) return o;
    const n = (seen.get(o.label) ?? 0) + 1;
    seen.set(o.label, n);
    return { ...o, label: `${o.label} (${n})` };
  });
}
