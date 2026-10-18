'use client';

import Link from 'next/link';

import { EmptyState } from '@/components/empty-state';
import { PageContainer, PageHeader } from '@/components/page-container';
import { Card } from '@/components/ui/card';
import { QueryStatus } from '@/components/query-status';

import { useListMemories } from '@/api-client/generated/memory/memory';
import { useListProposals } from '@/api-client/generated/proposals/proposals';
import { dateTime } from '@/lib/utils/format';

import { MemoryProposalCard, ProposalCard } from '@/features/advisor/components/proposal-card';

export function ApprovalsView() {
  const proposals = useListProposals({ status: 'pending' });
  const memories = useListMemories({ status: 'proposed' });
  const approved = useListProposals({ status: 'approved' });
  const rejected = useListProposals({ status: 'rejected' });
  const history = [...(approved.data ?? []), ...(rejected.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const empty =
    proposals.isSuccess && memories.isSuccess && !proposals.error && !memories.error && proposals.data?.length === 0 && memories.data?.length === 0;

  return (
    <PageContainer className='max-w-[820px]'>
      <PageHeader title='승인 대기' description='AI가 제안한 변경과 장기 기억입니다. 승인하기 전에는 아무것도 반영되지 않습니다.' />
      <QueryStatus pending={proposals.isPending} error={proposals.error} retry={proposals.refetch} label='승인 대기 제안' />
      <QueryStatus pending={memories.isPending} error={memories.error} retry={memories.refetch} label='확인 대기 기억' />
      {empty && (
        <Card>
          <EmptyState>승인할 항목이 없습니다.</EmptyState>
        </Card>
      )}
      <div className='flex flex-col gap-2.5'>
        {proposals.data?.map(p => (
          <div key={p.id}>
            <div className='mb-1 text-xs text-faint'>
              {dateTime(p.created_at)}{' '}
              {p.conversation_id && (
                <Link href={`/advisor/${p.conversation_id}`} className='text-primary hover:underline'>
                  · 상담 보기
                </Link>
              )}
            </div>
            <ProposalCard proposal={p} />
          </div>
        ))}
        {memories.data?.map(m => (
          <MemoryProposalCard key={m.id} memory={m} />
        ))}
      </div>

      <QueryStatus
        pending={approved.isPending || rejected.isPending}
        error={approved.error ?? rejected.error}
        retry={() => Promise.all([approved.refetch(), rejected.refetch()])}
        label='처리 내역'
      />
      {history.length > 0 && (
        <>
          <h2 className='mb-2.5 mt-7 text-[15px]'>처리 내역</h2>
          <div className='flex flex-col gap-2.5'>
            {history.slice(0, 20).map(p => (
              <ProposalCard key={p.id} proposal={p} />
            ))}
          </div>
        </>
      )}
    </PageContainer>
  );
}
