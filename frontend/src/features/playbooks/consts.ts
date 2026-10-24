import type { QueryClient } from '@tanstack/react-query';

import { getCountUnreadInboxQueryKey, getListInboxItemsQueryKey } from '@/api-client/generated/agent/agent';
import { getListPendingPlaybookRevisionsQueryKey, getListPlaybooksQueryKey } from '@/api-client/generated/playbooks/playbooks';

/** Why stored text was flagged. Model drafts with any of these are never saved. */
export const FINDING_LABEL: Record<string, string> = {
  prompt_injection: 'AI 지시·권한 변경으로 읽힐 수 있는 문장',
  secret: '키·토큰·비밀번호로 보이는 값',
  invisible_unicode: '보이지 않는 제어 문자',
  record_reference: '개인 기록 참조',
  personal_amount: '구체적인 금액',
  specific_date: '특정 날짜',
};

export const PLAYBOOK_STATUS: Record<string, string> = {
  proposed: '승인 전',
  active: '사용 중',
  archived: '보관됨',
  rejected: '거절됨',
};

export const REVISION_STATUS: Record<string, string> = {
  proposed: '제안',
  active: '현재 버전',
  superseded: '이전 버전',
  rejected: '거절됨',
};

/** Approval, edits and sharing change what consultations may send; refresh every view of it. */
export function invalidatePlaybooks(queryClient: QueryClient) {
  return Promise.all(
    [getListPlaybooksQueryKey(), getListPendingPlaybookRevisionsQueryKey(), getCountUnreadInboxQueryKey(), getListInboxItemsQueryKey()].map(queryKey =>
      queryClient.invalidateQueries({ queryKey }),
    ),
  ).then(() => queryClient.invalidateQueries({ predicate: query => String(query.queryKey[0]).startsWith('/api/playbooks/') }));
}

export function splitTriggers(value: string): string[] {
  return [...new Set(value.split(/[,\n]/).map(term => term.trim()).filter(term => term.length >= 2))].slice(0, 12);
}
