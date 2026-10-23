'use client';

import { useQueryClient } from '@tanstack/react-query';
import { Bell, CalendarClock, Lightbulb, PauseCircle, Sparkles, TriangleAlert } from 'lucide-react';
import Link from 'next/link';

import {
  getCountUnreadInboxQueryKey,
  getListInboxItemsQueryKey,
  useDismissInboxItem,
  useListInboxItems,
  useReadAllInbox,
  useReadInboxItem,
} from '@/api-client/generated/agent/agent';
import type { InboxItemView } from '@/api-client/model';
import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { PageContainer, PageHeader } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { relative } from '@/lib/utils/format';

/** Each kind is a different state: local signals, a briefing, learning to review, a paused schedule, a failure. */
const KIND: Record<string, { label: string; icon: typeof Bell; tone: 'default' | 'accent' | 'warning' | 'destructive' }> = {
  signal: { label: '확인할 항목', icon: CalendarClock, tone: 'default' },
  briefing_ready: { label: '브리핑', icon: Sparkles, tone: 'accent' },
  learning_proposals: { label: '학습 제안', icon: Lightbulb, tone: 'accent' },
  schedule_paused: { label: '예약 중지', icon: PauseCircle, tone: 'warning' },
  job_failed: { label: '실패', icon: TriangleAlert, tone: 'destructive' },
  playbook_source_purged: { label: '플레이북 확인 필요', icon: TriangleAlert, tone: 'warning' },
};

interface Signal {
  kind: string;
  title: string;
  count: number;
  link?: string | null;
}

function NextActions({ item }: { item: InboxItemView }) {
  const links = item.links as Record<string, unknown>;
  const signals = (Array.isArray(links.signals) ? links.signals : []) as Signal[];
  const actions: { href: string; label: string }[] = [];
  if (typeof links.conversation_id === 'number') actions.push({ href: `/advisor/${links.conversation_id}`, label: '상담 보기' });
  if (item.kind === 'learning_proposals' && (Array.isArray(links.playbook_revision_ids) || Array.isArray(links.memory_ids))) actions.push({ href: '/approvals', label: '제안 검토' });
  if (item.kind === 'schedule_paused' || item.kind === 'job_failed') actions.push({ href: '/settings/jobs', label: '자동 작업 확인' });
  if (typeof links.playbook_id === 'number') actions.push({ href: `/reflect/playbooks?record=${links.playbook_id}`, label: '플레이북 보기' });
  return (
    <div className='mt-1.5 flex flex-wrap gap-x-3 gap-y-1'>
      {signals.map(signal =>
        signal.link ? (
          <Link key={signal.kind} href={signal.link} className='text-xs text-primary hover:underline'>
            {signal.title} {signal.count}건
          </Link>
        ) : null,
      )}
      {actions.map(action => (
        <Link key={action.href} href={action.href} className='text-xs text-primary hover:underline'>
          {action.label}
        </Link>
      ))}
    </div>
  );
}

export function InboxView() {
  const queryClient = useQueryClient();
  const items = useListInboxItems(undefined, { query: { refetchInterval: 30000 } });
  const refresh = () =>
    Promise.all([getListInboxItemsQueryKey(), getCountUnreadInboxQueryKey()].map(queryKey => queryClient.invalidateQueries({ queryKey })));
  const options = { mutation: { onSuccess: refresh, onError: notify.error } };
  const read = useReadInboxItem(options);
  const dismiss = useDismissInboxItem(options);
  const readAll = useReadAllInbox(options);
  const unread = items.data?.filter(item => item.status === 'unread').length ?? 0;

  return (
    <PageContainer className='max-w-[820px]'>
      <PageHeader
        title='알림'
        description='자동 작업과 학습 결과입니다. 이 기기에서만 보이며 AI에 보내지 않습니다.'
        actions={
          unread > 0 && (
            <Button size='sm' disabled={readAll.isPending} onClick={() => readAll.mutate()}>
              모두 읽음
            </Button>
          )
        }
      />
      <QueryStatus pending={items.isPending} error={items.error} retry={items.refetch} label='알림' rows={3} />
      {items.data?.length === 0 && (
        <EmptyState
          icon={Bell}
          title='새 알림이 없습니다'
          action={
            <Button asChild size='sm'>
              <Link href='/settings/jobs'>브리핑 예약하기</Link>
            </Button>
          }>
          아침 브리핑을 예약하거나 상담에서 배우기를 요청하면 결과가 여기에 표시됩니다.
        </EmptyState>
      )}
      <ul className='flex flex-col gap-2'>
        {items.data?.map(item => {
          const kind = KIND[item.kind] ?? { label: '알림', icon: Bell, tone: 'default' as const };
          return (
            <li key={item.id} className={cn('rounded-lg border bg-card px-3.5 py-3', item.status === 'unread' && 'border-primary/40')}>
              <div className='flex flex-wrap items-center gap-2'>
                <kind.icon className={cn('size-4', kind.tone === 'warning' ? 'text-warning' : kind.tone === 'destructive' ? 'text-destructive' : 'text-primary')} aria-hidden />
                <span className='font-medium'>{item.title}</span>
                <Badge variant={kind.tone}>{kind.label}</Badge>
                {item.status === 'unread' && <span className='sr-only'>읽지 않음</span>}
                <span className='ml-auto text-2xs text-faint'>{relative(item.created_at)}</span>
              </div>
              {item.summary && <p className='mt-1 whitespace-pre-line text-ui text-muted-foreground'>{item.summary}</p>}
              <NextActions item={item} />
              <div className='mt-2 flex gap-1'>
                {item.status === 'unread' && (
                  <Button size='sm' variant='ghost' disabled={read.isPending} onClick={() => read.mutate({ itemId: item.id })}>
                    읽음
                  </Button>
                )}
                <Button size='sm' variant='ghost' disabled={dismiss.isPending} onClick={() => dismiss.mutate({ itemId: item.id })}>
                  지우기
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </PageContainer>
  );
}
