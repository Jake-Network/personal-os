import type { Category, SnapshotResponse } from '@/api-client/model';

import type { InspectorData } from '../types';

/** A revision refresh must not change retry identity; user-controlled payload fields must. */
export function sameRunIntent(left: Record<string, unknown>, right: Record<string, unknown>): boolean {
  const intent = (body: Record<string, unknown>) =>
    Object.fromEntries(
      Object.entries(body)
        .filter(([key, value]) => !['request_id', 'parent_revision'].includes(key) && value !== undefined)
        .sort(([a], [b]) => a.localeCompare(b)),
    );
  return JSON.stringify(intent(left)) === JSON.stringify(intent(right));
}

/** Per-request sharing: start from what the router picks, then apply the user's toggles. */
export function optionsFor(base: InspectorData, on: Set<Category>, off: Set<Category>): { categories?: Category[]; exclude: Category[] } {
  if (on.size === 0 || !base.route) return { exclude: [...off] };
  const categories = new Set<Category>([...base.route.requested, ...on]);
  off.forEach(c => categories.delete(c));
  return { categories: [...categories], exclude: [...off] };
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
    web_sources: (s.payload as { data?: { web_search?: { pages?: InspectorData['web_sources'] } } }).data?.web_search?.pages ?? [],
    categories: s.context_categories,
    excluded_categories: s.excluded_categories,
    source_updated_at: s.source_updated_at as InspectorData['source_updated_at'],
    record_references: s.record_references as unknown as InspectorData['record_references'],
    data_quality_flags: s.data_quality_flags as unknown as InspectorData['data_quality_flags'],
  };
}

export function publicWebUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

export function groupBy<T>(items: T[], key: (t: T) => string): Record<string, T[]> {
  return items.reduce<Record<string, T[]>>((acc, item) => {
    (acc[key(item)] ??= []).push(item);
    return acc;
  }, {});
}
