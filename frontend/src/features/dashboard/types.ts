import type { DashboardChecklist, DashboardSignal } from '@/api-client/model';
import type { DataFlag } from '@/features/advisor/types';

/** Typed dashboard envelope with the existing advisor tool output adapter. */
export interface DashboardSummary {
  generated_at: string;
  signals: DashboardSignal[];
  checklist: DashboardChecklist;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>;
  data_quality_flags: DataFlag[];
  source_updated_at: Record<string, string | null>;
  /** Cash runway from spendable liquidity only; `available: false` carries the reason instead of a guess. */
  computed: { runway: { available: boolean; months: string | null; reason?: string; understated?: boolean } | null };
}
