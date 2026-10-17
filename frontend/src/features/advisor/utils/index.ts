import type { Category, SnapshotResponse } from '@/api-client/model';

import type { InspectorData } from '../types';

/** Per-request sharing: start from what the router picks, then apply the user's toggles. */
export function optionsFor(base: InspectorData, on: Set<Category>, off: Set<Category>): { categories?: Category[]; exclude: Category[] } {
  if (on.size === 0 || !base.route) return { exclude: [...off] };
  const categories = new Set<Category>([...base.route.requested, ...on]);
  off.forEach(c => categories.delete(c));
  return { categories: [...categories], exclude: [] };
}

/** Proposal/memory blocks are rendered as cards, not as raw JSON. */
export function stripBlocks(text: string): string {
  return text.replace(/```(proposal|memory)[\s\S]*?(```|$)/g, '').trimEnd();
}

export function snapshotToInspector(s: SnapshotResponse): InspectorData {
  return {
    context_snapshot_id: s.context_snapshot_id,
    context_reused: false,
    document_citations:
      (s.payload as { data?: { search_documents?: { citations?: InspectorData['document_citations'] } } }).data?.search_documents?.citations ?? [],
    categories: s.context_categories,
    excluded_categories: s.excluded_categories,
    source_updated_at: s.source_updated_at as InspectorData['source_updated_at'],
    record_references: s.record_references as unknown as InspectorData['record_references'],
    data_quality_flags: s.data_quality_flags as unknown as InspectorData['data_quality_flags'],
  };
}

export function groupBy<T>(items: T[], key: (t: T) => string): Record<string, T[]> {
  return items.reduce<Record<string, T[]>>((acc, item) => {
    (acc[key(item)] ??= []).push(item);
    return acc;
  }, {});
}
