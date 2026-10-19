'use client';

import { Inbox } from 'lucide-react';
import Link from 'next/link';

import { EmptyState } from '@/components/empty-state';
import { PageContainer, PageHeader, Section } from '@/components/page-container';
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
  const empty = proposals.isSuccess && memories.isSuccess && proposals.data.length === 0 && memories.data.length === 0;

  return (
    <PageContainer className='max-w-[820px]'>
      <PageHeader title='승인 대기' description='상담에서 나온 변경 제안과 기억 후보입니다. 승인한 것만 반영됩니다.' />
      <QueryStatus pending={proposals.isPending} error={proposals.error} retry={proposals.refetch} label='변경 제안' />
      <QueryStatus pending={memories.isPending} error={memories.error} retry={memories.refetch} label='기억 후보' />
      {empty && <EmptyState icon={Inbox} title='기다리는 항목이 없습니다' className='rounded-lg border bg-card' />}

      {!!proposals.data?.length && (
        <Section title='변경 제안' count={proposals.data.length}>
          <div className='flex flex-col gap-3'>
            {proposals.data.map(p => (
              <div key={p.id}>
                <div className='mb-1 flex items-center gap-2 text-2xs text-faint'>
                  {dateTime(p.created_at)}
                  {p.conversation_id && (
                    <Link href={`/advisor/${p.conversation_id}`} className='text-primary hover:underline'>
                      상담 보기
                    </Link>
                  )}
                </div>
                <ProposalCard proposal={p} />
              </div>
            ))}
          </div>
        </Section>
      )}

      {!!memories.data?.length && (
        <Section title='기억 후보' count={memories.data.length}>
          <div className='flex flex-col gap-3'>
            {memories.data.map(m => (
              <MemoryProposalCard key={m.id} memory={m} />
            ))}
          </div>
        </Section>
      )}

      <QueryStatus
        pending={approved.isPending || rejected.isPending}
        error={approved.error ?? rejected.error}
        retry={() => Promise.all([approved.refetch(), rejected.refetch()])}
        label='처리 내역'
      />
      {history.length > 0 && (
        <Section title='최근 처리한 제안'>
          <div className='flex flex-col gap-3'>
            {history.slice(0, 20).map(p => (
              <ProposalCard key={p.id} proposal={p} />
            ))}
          </div>
        </Section>
      )}
    </PageContainer>
  );
}
