import type { Category, MemoryItem, ProposalItem } from '@/api-client/model';

// The preview, snapshot-stream and dashboard endpoints return untyped dicts in OpenAPI; these mirror the backend shape.

export interface DataFlag {
  code: string;
  category: string;
  detail?: string;
}

export interface RecordRef {
  table?: string;
  id?: number;
  count?: number;
  since?: string;
  updated_at?: string | null;
  category: string;
  tool: string;
}

export interface RouteInfo {
  requested: Category[];
  selected: Category[];
  excluded: Category[];
  matched_terms: string[];
  reason: 'keyword' | 'override' | 'previous_turn' | 'domain' | 'fallback';
}

export interface InspectorData {
  route?: RouteInfo;
  context_snapshot_id: string | null;
  context_reused: boolean;
  categories: string[];
  excluded_categories: string[];
  source_updated_at: Record<string, string | null>;
  record_references: RecordRef[];
  data_quality_flags: DataFlag[];
  /** Earlier messages not replayed because they may hold data from a now-excluded category. */
  history_withheld_messages?: number;
  history_withheld_categories?: string[];
}

export type InspectorMode = 'preview' | 'answer' | 'snapshot';

export type MemoryProposal = Pick<MemoryItem, 'id' | 'kind' | 'content'> & { status?: string };

/** Events from POST /api/advisor/conversations/{id}/messages */
export type AdvisorEvent =
  | ({ type: 'context' } & InspectorData)
  | { type: 'delta'; text: string }
  | { type: 'done'; message_id: number; context_snapshot_id: string; proposals: ProposalItem[]; memory_proposals: MemoryProposal[] }
  | { type: 'error'; code: string; message: string; provider_code: string | null };

export interface ChatMessage {
  key: string;
  id?: number;
  role: 'user' | 'assistant';
  content: string;
  status: 'complete' | 'incomplete' | 'failed';
  context_snapshot_id: string | null;
  model: string | null;
  created_at?: string;
  streaming?: boolean;
  error?: { code: string; message: string };
  proposals?: ProposalItem[];
  memoryProposals?: MemoryProposal[];
}
