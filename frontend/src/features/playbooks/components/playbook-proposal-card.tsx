'use client';

import { useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';

import { errorMessage } from '@/api-client/api-error';
import {
  useApprovePlaybookRevision,
  useGetPlaybookRevisionDiff,
  useRejectPlaybookRevision,
} from '@/api-client/generated/playbooks/playbooks';
import type { PlaybookRevisionItem } from '@/api-client/model';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CATEGORY_LABEL } from '@/lib/labels';
import { cn } from '@/lib/utils';
import { dateTime } from '@/lib/utils/format';

import { invalidatePlaybooks } from '../consts';

export function DiffView({ revisionId }: { revisionId: number }) {
  const diff = useGetPlaybookRevisionDiff(revisionId);
  if (diff.isPending) return <p className='text-xs text-faint'>비교하는 중…</p>;
  if (diff.error) return <Alert variant='destructive'>{errorMessage(diff.error)}</Alert>;
  const lines = diff.data.diff.split('\n').filter(line => !line.startsWith('---') && !line.startsWith('+++') && !line.startsWith('@@'));
  return (
    <pre className='max-h-80 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/40 p-2 text-xs' aria-label='바뀐 내용'>
      {lines.map((line, index) => (
        <div
          key={index}
          className={cn(line.startsWith('+') && 'bg-success-soft text-success', line.startsWith('-') && 'bg-destructive-soft text-destructive')}>
          {line || ' '}
        </div>
      ))}
    </pre>
  );
}

/** A model-written procedure. Nothing is used in consultations until the user approves it. */
export function PlaybookProposalCard({ revision }: { revision: PlaybookRevisionItem }) {
  const queryClient = useQueryClient();
  const [showDiff, setShowDiff] = useState(false);
  const options = { mutation: { onSuccess: () => invalidatePlaybooks(queryClient) } };
  const approve = useApprovePlaybookRevision(options);
  const reject = useRejectPlaybookRevision(options);
  const state = approve.isSuccess ? 'approved' : reject.isSuccess ? 'rejected' : undefined;
  const busy = approve.isPending || reject.isPending;
  const error = approve.error ?? reject.error;
  const blocked = revision.stale || revision.source_purged;

  return (
    <div className='rounded-lg border bg-card px-3.5 py-3 shadow-sm'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-ui font-semibold'>{revision.base_revision_id ? '플레이북 수정 제안' : '새 플레이북 제안'}</span>
        <span className='text-ui'>{revision.title}</span>
        <span className='flex-1' />
        {revision.stale && <Badge variant='warning'>그 사이 플레이북이 바뀜</Badge>}
        {revision.source_purged && <Badge variant='warning'>근거가 삭제됨</Badge>}
        {state === 'approved' && <Badge variant='success'>승인함</Badge>}
        {state === 'rejected' && <Badge>거절됨</Badge>}
      </div>
      <p className='mt-1 text-xs text-muted-foreground'>{revision.summary}</p>
      <div className='mt-1.5 flex flex-wrap items-center gap-1.5 text-2xs text-faint'>
        {dateTime(revision.created_at)}
        {revision.categories.map(category => (
          <Badge key={category}>{CATEGORY_LABEL[category as keyof typeof CATEGORY_LABEL] ?? category}</Badge>
        ))}
        <Link href={`/reflect/playbooks?record=${revision.playbook_id}`} className='text-primary hover:underline'>
          플레이북 보기
        </Link>
      </div>
      {revision.rationale && <p className='mt-2 text-xs text-muted-foreground'>제안 이유: {revision.rationale}</p>}
      <Button size='sm' variant='ghost' className='mt-1 px-0' aria-expanded={showDiff} onClick={() => setShowDiff(v => !v)}>
        {showDiff ? '바뀐 내용 접기' : '바뀐 내용 보기'}
      </Button>
      {showDiff && <DiffView revisionId={revision.id} />}
      {error && (
        <Alert variant='destructive' className='mt-2'>
          {errorMessage(error)}
        </Alert>
      )}
      {!state && (
        <div className='mt-2 flex flex-wrap items-center gap-2'>
          <Button size='sm' variant='primary' disabled={busy || blocked} onClick={() => approve.mutate({ revisionId: revision.id })}>
            {approve.isPending ? '승인하는 중…' : '승인하고 사용'}
          </Button>
          <Button size='sm' variant='ghost' disabled={busy} onClick={() => reject.mutate({ revisionId: revision.id })}>
            거절
          </Button>
          <span className='text-2xs text-faint'>
            {blocked ? '이 제안은 승인할 수 없습니다. 거절하고 필요하면 다시 배우기를 요청하세요.' : '승인하기 전에는 상담에 쓰지 않습니다.'}
          </span>
        </div>
      )}
    </div>
  );
}
