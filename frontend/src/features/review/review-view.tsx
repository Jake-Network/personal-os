'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';

import { useCountUnreadInbox } from '@/api-client/generated/agent/agent';
import { useListDecisions, useListMemories } from '@/api-client/generated/memory/memory';
import { useListPendingPlaybookRevisions } from '@/api-client/generated/playbooks/playbooks';
import { useListProposals } from '@/api-client/generated/proposals/proposals';
import { PageContainer, PageHeader, Section } from '@/components/page-container';
import { Button } from '@/components/ui/button';
import { ApprovalsView } from '@/features/approvals/components/approvals-view';
import { InboxView } from '@/features/inbox/inbox-view';
import { isDecisionReviewDue } from '@/features/memory/review-due';
import { recordHref } from '@/features/personal-data/hooks/use-record-param';
import { dateOnly } from '@/lib/utils/format';

import type { ReviewFilter } from './filters';


/** Counts behind the single "검토함" entry: pending approvals, due decision reviews and unread notifications. */
export function useReviewCounts() {
  const poll = { query: { refetchInterval: 30000 } };
  const approvals =
    (useListProposals({ status: 'pending' }, poll).data?.length ?? 0) +
    (useListMemories({ status: 'proposed' }, poll).data?.length ?? 0) +
    (useListPendingPlaybookRevisions(poll).data?.length ?? 0);
  const decisions = (useListDecisions().data ?? []).filter(d => isDecisionReviewDue(d)).length;
  const inbox = useCountUnreadInbox(poll).data?.unread ?? 0;
  return { approvals, decisions, inbox, total: approvals + decisions + inbox };
}

function DueDecisions() {
  const due = (useListDecisions().data ?? []).filter(d => isDecisionReviewDue(d));
  return (
    <Section title='회고할 결정' count={due.length || undefined}>
      {due.length === 0 ? (
        <p className='py-2 text-ui text-muted-foreground'>회고 날짜가 된 결정이 없습니다.</p>
      ) : (
        <ul className='divide-y rounded-lg border bg-card px-3.5'>
          {due.map(d => (
            <li key={d.id} className='flex flex-wrap items-center gap-2 py-2.5 text-ui'>
              <span className='min-w-0 flex-1 truncate font-medium'>{d.title}</span>
              {d.review_on && <span className='text-xs text-faint'>회고일 {dateOnly(d.review_on)}</span>}
              <Button asChild size='sm'>
                <Link href={recordHref('/reflect', d.id)}>결과 기록</Link>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

/** One place for everything waiting on the user. Nothing here is sent to the model. */
export function ReviewView({ filter }: { filter: ReviewFilter }) {
  const router = useRouter();
  const pathname = usePathname();
  const counts = useReviewCounts();
  const chips: [ReviewFilter, string, number][] = [
    ['all', '전체', counts.total],
    ['approvals', '승인 대기', counts.approvals],
    ['decisions', '회고할 결정', counts.decisions],
    ['inbox', '알림', counts.inbox],
  ];
  const show = (section: ReviewFilter) => filter === 'all' || filter === section;
  return (
    <PageContainer className='max-w-[820px]'>
      <PageHeader title='검토함' description='승인할 제안·기억·절차, 회고할 결정과 알림을 모았습니다. 승인한 것만 반영되며, 이 화면의 내용은 AI에 보내지 않습니다.' />
      <div className='mb-5 flex flex-wrap gap-2' role='group' aria-label='검토함 보기'>
        {chips.map(([value, label, count]) => (
          <Button
            key={value}
            size='sm'
            aria-pressed={filter === value}
            variant={filter === value ? 'primary' : 'default'}
            onClick={() => router.replace(value === 'all' ? pathname : `${pathname}?view=${value}`)}>
            {label}
            {count > 0 && <span className='tabular-nums'>{count}</span>}
          </Button>
        ))}
      </div>
      {show('approvals') && (
        <section aria-label='승인 대기' className='mb-6'>
          {filter === 'all' && <h2 className='mb-2 text-ui font-semibold text-muted-foreground'>승인 대기</h2>}
          <ApprovalsView embedded />
        </section>
      )}
      {show('decisions') && <DueDecisions />}
      {show('inbox') && (
        <section aria-label='알림' className='mb-6'>
          <h2 className='mb-2 text-ui font-semibold text-muted-foreground'>알림</h2>
          <InboxView embedded />
        </section>
      )}
    </PageContainer>
  );
}
