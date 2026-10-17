import type { DataFlag } from '@/features/advisor/types';

/** GET /api/dashboard/summary: the advisor tools' outputs keyed by tool name (untyped in OpenAPI). */
export interface DashboardSummary {
  generated_at: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>;
  data_quality_flags: DataFlag[];
  source_updated_at: Record<string, string | null>;
  computed: { runway: { months: string | null } | null };
}
