import type { RunCreate } from '@/api-client/model';

import { sameRunIntent } from './index';

/** Per-question options the user sets around the composer. They belong to one conversation view. */
export interface DraftOptions {
  documentSearch: boolean;
  /** null = search by topic (and inherit the previous turn's documents); [] = explicitly cleared. */
  documentIds: number[] | null;
  webSearch: boolean;
  webQuery: string;
  allowDataRecording: boolean;
  depth: 'auto' | 'deep';
  historyCompany: string;
  historyProject: string;
  historyDecision: string;
}

export const MAX_DOCUMENTS = 5;

/** A fresh draft; a new consultation opened from a document starts with that document selected. */
export function initialDraft(conversationId: number | null, documentParam: string | null): DraftOptions {
  const id = Number(documentParam);
  return {
    documentSearch: true,
    documentIds: conversationId === null && Number.isSafeInteger(id) && id > 0 ? [id] : null,
    webSearch: false,
    webQuery: '',
    allowDataRecording: false,
    depth: 'auto',
    historyCompany: '',
    historyProject: '',
    historyDecision: '',
  };
}

/** The request fields that come from the draft (sent with both preview and run creation). */
export function documentOptionsOf(d: DraftOptions) {
  return {
    document_search: d.documentSearch,
    document_ids: d.documentIds,
    history_company: d.historyCompany || null,
    history_project: d.historyProject ? Number(d.historyProject) : null,
    history_decision: d.historyDecision ? Number(d.historyDecision) : null,
    web_search: d.webSearch,
    web_query: d.webSearch ? d.webQuery.trim() : null,
    allow_data_recording: d.allowDataRecording,
  };
}

export type SubmitBlock = 'empty' | 'locked' | 'busy' | 'provider' | 'share_pending' | 'web_query';

/** Why a submit must not go out now; null when it may. Clarification answers skip the new-question checks. */
export function submitBlock(s: {
  text: string;
  locked: boolean;
  sending: boolean;
  busy: boolean;
  waiting: boolean;
  providerNeedsSetup: boolean;
  forcedOnCount: number;
  hasBaseline: boolean;
  webSearch: boolean;
  webQuery: string;
}): SubmitBlock | null {
  if (!s.text.trim()) return 'empty';
  if (s.locked || s.sending) return 'locked';
  if (s.busy && !s.waiting) return 'busy';
  if (s.providerNeedsSetup) return 'provider';
  if (!s.waiting && s.forcedOnCount > 0 && !s.hasBaseline) return 'share_pending';
  if (!s.waiting && s.webSearch && !s.webQuery.trim()) return 'web_query';
  return null;
}

export const SUBMIT_BLOCK_MESSAGE: Partial<Record<SubmitBlock, string>> = {
  share_pending: '바꾼 공유 범위를 확인하는 중입니다. 확인이 끝나면 다시 보내 주세요.',
  web_query: '웹 검색에 쓸 공개 검색어를 입력해 주세요.',
};

export interface PendingRequest {
  conversationId: number;
  body: RunCreate;
}

/**
 * A request whose save is uncertain is resent with the same request ID only if the user changed nothing
 * that matters; a changed question must first be reconciled with the server, never silently reuse the old body.
 */
export function planRunRequest(
  previous: PendingRequest | null,
  candidate: RunCreate,
  conversationId: number,
): { action: 'send'; body: RunCreate } | { action: 'reconcile' } {
  if (previous?.conversationId !== conversationId) return { action: 'send', body: candidate };
  if (sameRunIntent({ ...previous.body }, { ...candidate })) return { action: 'send', body: previous.body };
  return { action: 'reconcile' };
}
