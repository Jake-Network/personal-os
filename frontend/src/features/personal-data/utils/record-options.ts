import { TRANSACTION_KIND_LABEL } from '@/features/finance/transaction-kinds';

export type RecordOption = { value: string; label: string };

// Labels are presentation only. The option value always retains the server record ID.
export function recordOptions(rows: Array<Record<string, unknown> & { id: number }>): RecordOption[] {
  return rows.map(row => {
    const title = row.company
      ? [...new Set([row.company, row.title, row.role].filter(Boolean))].join(' · ')
      : (row.name ??
        row.title ??
        row.content ??
        row.symbol ??
        [
          row.occurred_on ?? row.occurred_at,
          row.kind ? (TRANSACTION_KIND_LABEL[String(row.kind)] ?? row.kind) : null,
          row.amount != null ? [row.amount, row.currency].filter(v => v != null && v !== '').join(' ') : null,
          row.description ?? row.note,
          row.category,
        ]
          .filter(Boolean)
          .join(' · '));
    return { value: String(row.id), label: `${title || '이름 없는 기록'} (#${row.id})` };
  });
}
