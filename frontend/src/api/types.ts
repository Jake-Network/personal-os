export type Category = 'financial' | 'investment' | 'career' | 'calendar' | 'health' | 'goals' | 'profile';

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
}

export interface Conversation {
  id: number;
  title: string;
  domain: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant';
  content: string;
  status: 'complete' | 'incomplete' | 'failed';
  context_snapshot_id: string | null;
  model: string | null;
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface Proposal {
  id: number;
  action: 'create_task' | 'calendar_update' | 'goal_update';
  payload: Record<string, unknown>;
  rationale: string | null;
  status?: string;
  conversation_id?: number | null;
  created_at?: string;
  result_ref?: Record<string, unknown> | null;
}

export interface Memory {
  id: number;
  kind: 'profile' | 'preference' | 'constraint' | 'priority';
  content: string;
  status: string;
  source: string;
  created_at: string;
  confirmed_at: string | null;
}

export interface Decision {
  id: number;
  title: string;
  decided_at: string;
  context_snapshot_id: string | null;
  conversation_id: number | null;
  alternatives: string[];
  choice: string;
  rationale: string;
  expected_outcome: string | null;
  review_on: string | null;
  actual_outcome: string | null;
  reviewed_at: string | null;
}

export interface Snapshot {
  context_snapshot_id: string;
  conversation_id: number | null;
  generated_at: string;
  context_categories: string[];
  excluded_categories: string[];
  record_references: RecordRef[];
  source_updated_at: Record<string, string | null>;
  data_quality_flags: DataFlag[];
  payload: Record<string, any>;
}

export interface SnapshotCompare {
  context_snapshot_id: string;
  snapshot_generated_at: string;
  compared_at: string;
  changed_sections: string[];
  unchanged_sections: string[];
}

export interface ProviderStatus {
  connected: boolean;
  status: 'connected' | 'needs_reauth' | 'disconnected' | null;
  email: string | null;
  display_name: string | null;
  plan_usage_enabled: boolean;
  scopes: string[];
  access_expires_at: string | null;
  last_error_code: string | null;
  provider: string;
  model: string | null;
  usage_url: string;
}

export interface UsageEvent {
  id: number;
  provider: string;
  model: string | null;
  outcome: string;
  error_code: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  created_at: string;
}

export interface DashboardSummary {
  generated_at: string;
  data: Record<string, any>;
  data_quality_flags: DataFlag[];
  source_updated_at: Record<string, string | null>;
  computed: { runway: { months: string | null } | null };
}

/** Events from POST /api/advisor/conversations/{id}/messages */
export type AdvisorEvent =
  | ({ type: 'context' } & InspectorData)
  | { type: 'delta'; text: string }
  | {
      type: 'done';
      message_id: number;
      context_snapshot_id: string;
      proposals: Proposal[];
      memory_proposals: Pick<Memory, 'id' | 'kind' | 'content'>[];
    }
  | { type: 'error'; code: string; message: string; provider_code: string | null };
