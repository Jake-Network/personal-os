'use client';

import { useQueryClient } from '@tanstack/react-query';

import { useDecideApprovals } from '@/api-client/generated/approvals/approvals';
import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';
import { getListMemoriesQueryKey } from '@/api-client/generated/memory/memory';
import { getListCalendarEventsQueryKey, getListGoalsQueryKey, getListTasksQueryKey } from '@/api-client/generated/personal-data/personal-data';
import { getListProposalsQueryKey } from '@/api-client/generated/proposals/proposals';
import type { ApprovalBatchResult, ApprovalDecisionKind } from '@/api-client/model';
import { notify } from '@/components/notify';

import { invalidatePlaybooks } from '@/features/playbooks/consts';

export type ApprovalKey = `${ApprovalDecisionKind}:${number}`;

export const approvalKey = (kind: ApprovalDecisionKind, id: number): ApprovalKey => `${kind}:${id}`;

export function parseApprovalKey(key: ApprovalKey): { kind: ApprovalDecisionKind; id: number } {
  const [kind, id] = key.split(':');
  return { kind: kind as ApprovalDecisionKind, id: Number(id) };
}

/** Short Korean summary of a batch; failures keep the server's reason (stale base, already decided…). */
export function batchSummary(result: ApprovalBatchResult, verb: string): { ok: boolean; message: string } {
  if (result.failed === 0) return { ok: true, message: `${result.succeeded}건을 ${verb}했습니다` };
  const reasons = [...new Set(result.results.filter(item => !item.ok).map(item => item.error ?? '처리하지 못했습니다'))];
  return {
    ok: false,
    message: `${result.succeeded}건 ${verb}, ${result.failed}건은 처리하지 못했습니다: ${reasons.slice(0, 2).join(' / ')}`,
  };
}

/**
 * Decides several items the user selected on screen in one request. Each item is still decided
 * separately on the server, so a stale or already-decided item never undoes the others.
 */
export function useBatchDecision(onDone?: (result: ApprovalBatchResult) => void) {
  const queryClient = useQueryClient();
  const mutation = useDecideApprovals({
    mutation: {
      onSuccess: async (result, variables) => {
        await Promise.all([
          ...[
            getListProposalsQueryKey(),
            getListMemoriesQueryKey(),
            getListTasksQueryKey(),
            getListCalendarEventsQueryKey(),
            getListGoalsQueryKey(),
            getSummaryQueryKey(),
            ['advisor-workspace'],
          ].map(queryKey => queryClient.invalidateQueries({ queryKey })),
          invalidatePlaybooks(queryClient),
        ]);
        const verb = variables.data.items.every(item => item.decision === 'approve')
          ? '승인'
          : variables.data.items.every(item => item.decision === 'reject')
            ? '거절'
            : '처리';
        const summary = batchSummary(result, verb);
        if (summary.ok) notify.success(summary.message);
        else notify.error(summary.message);
        onDone?.(result);
      },
      onError: notify.error,
    },
  });
  const decide = (keys: ApprovalKey[], decision: 'approve' | 'reject') =>
    mutation.mutate({ data: { items: keys.map(key => ({ ...parseApprovalKey(key), decision })) } });
  return { decide, isPending: mutation.isPending };
}
