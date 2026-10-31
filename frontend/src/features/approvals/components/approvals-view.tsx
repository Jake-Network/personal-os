'use client';

import { useState, type ReactNode } from 'react';

import { Inbox } from 'lucide-react';
import Link from 'next/link';

import { EmptyState } from '@/components/empty-state';
import { PageContainer, PageHeader, Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';

import { useListMemories } from '@/api-client/generated/memory/memory';
import { useListPendingPlaybookRevisions } from '@/api-client/generated/playbooks/playbooks';
import { useListProposals } from '@/api-client/generated/proposals/proposals';
import { dateTime } from '@/lib/utils/format';

import { MemoryProposalCard, ProposalCard } from '@/features/advisor/components/proposal-card';
import { PlaybookProposalCard } from '@/features/playbooks/components/playbook-proposal-card';

import { approvalKey, useBatchDecision, type ApprovalKey } from '../batch';

/** A card with a checkbox; the card's own buttons still decide just that item. */
function Selectable({
  id,
  label,
  checked,
  onChange,
  children,
}: {
  id: ApprovalKey;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
}) {
  return (
    <div className='flex items-start gap-2.5'>
      <Checkbox
        id={`select-${id}`}
        className='mt-3.5'
        checked={checked}
        onCheckedChange={value => onChange(value === true)}
        aria-label={`${label} 선택`}
      />
      <div className='min-w-0 flex-1'>{children}</div>
    </div>
  );
}

/** Pending approvals; `embedded` renders the body only, inside the review inbox. */
export function ApprovalsView({ embedded = false }: { embedded?: boolean }) {
  const proposals = useListProposals({ status: 'pending' }, { query: { refetchInterval: 30000 } });
  const memories = useListMemories({ status: 'proposed' }, { query: { refetchInterval: 30000 } });
  const playbooks = useListPendingPlaybookRevisions({ query: { refetchInterval: 30000 } });
  const approved = useListProposals({ status: 'approved' });
  const rejected = useListProposals({ status: 'rejected' });
  const history = [...(approved.data ?? []), ...(rejected.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const empty =
    proposals.isSuccess &&
    memories.isSuccess &&
    playbooks.isSuccess &&
    proposals.data.length === 0 &&
    memories.data.length === 0 &&
    playbooks.data.length === 0;

  const [selected, setSelected] = useState<Set<ApprovalKey>>(new Set());
  const batch = useBatchDecision(() => setSelected(new Set()));
  const pending: ApprovalKey[] = [
    ...(proposals.data ?? []).map(p => approvalKey('action', p.id)),
    ...(memories.data ?? []).map(m => approvalKey('memory', m.id)),
    ...(playbooks.data ?? []).map(r => approvalKey('playbook', r.id)),
  ];
  // Items decided elsewhere (another tab, the card's own button) drop out of the selection.
  const chosen = pending.filter(key => selected.has(key));
  const blocked = new Set((playbooks.data ?? []).filter(r => r.stale || r.source_purged).map(r => approvalKey('playbook', r.id)));
  const approvable = chosen.filter(key => !blocked.has(key));
  const toggle = (key: ApprovalKey) => (checked: boolean) =>
    setSelected(current => {
      const next = new Set(current);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  const sectionToggle = (keys: ApprovalKey[]) => {
    const all = keys.length > 0 && keys.every(key => selected.has(key));
    return (
      <Button
        size='sm'
        variant='ghost'
        onClick={() =>
          setSelected(current => {
            const next = new Set(current);
            keys.forEach(key => (all ? next.delete(key) : next.add(key)));
            return next;
          })
        }>
        {all ? '선택 해제' : '모두 선택'}
      </Button>
    );
  };

  const body = (
    <>
      <QueryStatus pending={proposals.isPending} error={proposals.error} retry={proposals.refetch} label='변경 제안' />
      <QueryStatus pending={memories.isPending} error={memories.error} retry={memories.refetch} label='기억 후보' />
      <QueryStatus pending={playbooks.isPending} error={playbooks.error} retry={playbooks.refetch} label='플레이북 제안' />
      {empty && <EmptyState icon={Inbox} title='승인을 기다리는 항목이 없습니다' className='rounded-lg border bg-card' />}

      {chosen.length > 0 && (
        <div
          className='sticky top-2 z-10 mb-4 flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3 py-2 shadow-sm'
          role='region'
          aria-label='선택한 항목 처리'>
          <span className='text-ui font-medium'>{chosen.length}건 선택</span>
          {approvable.length < chosen.length && (
            <span className='text-2xs text-faint'>바뀌었거나 근거가 삭제된 플레이북 제안은 승인에서 빠집니다</span>
          )}
          <span className='flex-1' />
          <Button
            size='sm'
            variant='primary'
            disabled={batch.isPending || approvable.length === 0}
            onClick={() => batch.decide(approvable, 'approve')}>
            {batch.isPending ? '처리하는 중…' : `${approvable.length}건 승인`}
          </Button>
          <Button size='sm' variant='ghost' disabled={batch.isPending} onClick={() => batch.decide(chosen, 'reject')}>
            {chosen.length}건 거절
          </Button>
          <Button size='sm' variant='ghost' disabled={batch.isPending} onClick={() => setSelected(new Set())}>
            선택 해제
          </Button>
        </div>
      )}

      {!!proposals.data?.length && (
        <Section title='변경 제안' count={proposals.data.length} actions={sectionToggle(proposals.data.map(p => approvalKey('action', p.id)))}>
          <div className='flex flex-col gap-3'>
            {proposals.data.map(p => {
              const key = approvalKey('action', p.id);
              return (
                <Selectable key={p.id} id={key} label='변경 제안' checked={selected.has(key)} onChange={toggle(key)}>
                  <div className='mb-1 flex items-center gap-2 text-2xs text-faint'>
                    {dateTime(p.created_at)}
                    {p.conversation_id && (
                      <Link href={`/advisor/${p.conversation_id}`} className='text-primary hover:underline'>
                        상담 보기
                      </Link>
                    )}
                  </div>
                  <ProposalCard proposal={p} />
                </Selectable>
              );
            })}
          </div>
        </Section>
      )}

      {!!memories.data?.length && (
        <Section title='기억 후보' count={memories.data.length} actions={sectionToggle(memories.data.map(m => approvalKey('memory', m.id)))}>
          <div className='flex flex-col gap-3'>
            {memories.data.map(m => {
              const key = approvalKey('memory', m.id);
              return (
                <Selectable key={m.id} id={key} label='기억 후보' checked={selected.has(key)} onChange={toggle(key)}>
                  <MemoryProposalCard memory={m} />
                </Selectable>
              );
            })}
          </div>
        </Section>
      )}

      {!!playbooks.data?.length && (
        <Section title='플레이북 제안' count={playbooks.data.length} actions={sectionToggle(playbooks.data.map(r => approvalKey('playbook', r.id)))}>
          <div className='flex flex-col gap-3'>
            {playbooks.data.map(r => {
              const key = approvalKey('playbook', r.id);
              return (
                <Selectable key={r.id} id={key} label={`${r.title} 플레이북 제안`} checked={selected.has(key)} onChange={toggle(key)}>
                  <PlaybookProposalCard revision={r} />
                </Selectable>
              );
            })}
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
    </>
  );
  if (embedded) return body;
  return (
    <PageContainer className='max-w-[820px]'>
      <PageHeader title='승인 대기' description='상담에서 나온 변경 제안, 기억 후보와 배운 절차입니다. 승인한 것만 반영됩니다.' />
      {body}
    </PageContainer>
  );
}
