'use client';

import { useQueryClient } from '@tanstack/react-query';

import { notify } from '@/components/notify';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

import { errorMessage } from '@/api-client/api-error';
import { getListMemoriesQueryKey, useConfirmMemory, useRejectMemory, useListMemories } from '@/api-client/generated/memory/memory';
import { getListProposalsQueryKey, useApprove, useReject } from '@/api-client/generated/proposals/proposals';
import { getListTasksQueryKey, getListCalendarEventsQueryKey, getListGoalsQueryKey } from '@/api-client/generated/personal-data/personal-data';
import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';
import type { ProposalItem } from '@/api-client/model';
import { ACTION_LABEL, MEMORY_KIND_LABEL } from '@/lib/labels';

import { enumLabel, fieldLabel } from '@/features/personal-data/consts/resources';

import type { MemoryProposal } from '../types';

const cardClass = 'rounded-lg border border-dashed border-input bg-card px-3 py-2.5';

type Proposal = Pick<ProposalItem, 'id' | 'action' | 'payload' | 'rationale'> & { status?: string };

export function ProposalCard({ proposal }: { proposal: Proposal }) {
  const queryClient = useQueryClient();
  const options = {
    mutation: {
      onSuccess: () =>
        Promise.all(
          [
            getListProposalsQueryKey(),
            getListTasksQueryKey(),
            getListCalendarEventsQueryKey(),
            getListGoalsQueryKey(),
            getSummaryQueryKey(),
            ['advisor-workspace'],
          ].map(queryKey => queryClient.invalidateQueries({ queryKey })),
        ),
    },
  };
  const approve = useApprove(options);
  const reject = useReject(options);

  const state = approve.isSuccess ? 'approved' : reject.isSuccess ? 'rejected' : proposal.status !== 'pending' ? proposal.status : undefined;
  const busy = approve.isPending || reject.isPending;
  const error = approve.error ?? reject.error;
  const before =
    proposal.payload._before && typeof proposal.payload._before === 'object' ? (proposal.payload._before as Record<string, unknown>) : {};

  return (
    <div className={cardClass}>
      <div className='flex items-center gap-2'>
        <Badge variant='accent'>제안 · {ACTION_LABEL[proposal.action] ?? proposal.action}</Badge>
        <span className='flex-1' />
        {state === 'approved' && <Badge variant='success'>승인되어 반영됨</Badge>}
        {state === 'rejected' && <Badge>거절됨</Badge>}
      </div>
      <dl className='my-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs'>
        {Object.entries(proposal.payload)
          .filter(([key]) => !key.startsWith('_'))
          .map(([k, v]) => (
            <div key={k} className='contents'>
              <dt className='text-muted-foreground'>{fieldLabel(k)}</dt>
              <dd>
                {k in before && <span className='text-muted-foreground'>{enumLabel(before[k])} → </span>}
                {enumLabel(v)}
              </dd>
            </div>
          ))}
      </dl>
      {proposal.rationale && <div className='mb-2 text-xs text-faint'>{proposal.rationale}</div>}
      {error && (
        <Alert variant='destructive' className='mb-2'>
          {errorMessage(error)}
        </Alert>
      )}
      {!state && (
        <div className='flex flex-wrap items-center gap-2'>
          <Button size='sm' variant='primary' disabled={busy} onClick={() => approve.mutate({ proposalId: proposal.id })}>
            승인하고 반영
          </Button>
          <Button size='sm' disabled={busy} onClick={() => reject.mutate({ proposalId: proposal.id })}>
            거절
          </Button>
          <span className='text-xs text-faint'>승인 전에는 아무것도 변경되지 않습니다.</span>
        </div>
      )}
    </div>
  );
}

export function MemoryProposalCard({ memory }: { memory: MemoryProposal }) {
  const queryClient = useQueryClient();
  const queryOptions = { query: { refetchInterval: 5000 } };
  const proposed = useListMemories({ status: 'proposed' }, queryOptions);
  const confirmed = useListMemories({ status: 'confirmed' }, queryOptions);
  const rejected = useListMemories({ status: 'rejected' }, queryOptions);
  const current = [...(proposed.data ?? []), ...(confirmed.data ?? []), ...(rejected.data ?? [])].find(item => item.id === memory.id);
  const loading = proposed.isPending || confirmed.isPending || rejected.isPending;
  const loadError = proposed.error ?? confirmed.error ?? rejected.error;
  const options = {
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListMemoriesQueryKey() }),
          queryClient.invalidateQueries({ queryKey: ['advisor-workspace'] }),
          queryClient.invalidateQueries({ predicate: query => String(query.queryKey[0]).startsWith('/api/advisor/conversations') }),
        ]),
      onError: notify.error,
    },
  };
  const confirmMemory = useConfirmMemory(options);
  const rejectMemory = useRejectMemory(options);

  const state = confirmMemory.isSuccess
    ? 'confirmed'
    : rejectMemory.isSuccess
      ? 'rejected'
      : loading
        ? 'loading'
        : loadError
          ? 'unavailable'
          : current
            ? current.status === 'proposed'
              ? undefined
              : current.status
            : 'deleted';
  const busy = confirmMemory.isPending || rejectMemory.isPending;

  return (
    <div className={cardClass}>
      <div className='flex items-center gap-2'>
        <Badge variant='accent'>기억 제안 · {MEMORY_KIND_LABEL[memory.kind] ?? memory.kind}</Badge>
        <span className='flex-1' />
        {state === 'confirmed' && <Badge variant='success'>저장됨</Badge>}
        {state === 'rejected' && <Badge>저장 안 함</Badge>}
        {state === 'deleted' && <Badge>삭제됨</Badge>}
      </div>
      <div className='my-2'>{state === 'deleted' ? '이 기억 후보는 삭제되었습니다.' : (current?.content ?? memory.content)}</div>
      {loadError && <Alert variant='destructive'>{errorMessage(loadError)}</Alert>}
      {!state && (
        <div className='flex gap-2'>
          <Button size='sm' variant='primary' disabled={busy} onClick={() => confirmMemory.mutate({ memoryId: memory.id })}>
            장기 기억에 저장
          </Button>
          <Button size='sm' disabled={busy} onClick={() => rejectMemory.mutate({ memoryId: memory.id })}>
            이번 상담에만 남기기
          </Button>
        </div>
      )}
    </div>
  );
}
