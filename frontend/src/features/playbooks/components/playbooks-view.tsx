'use client';

import { useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import { BookOpenCheck, Plus } from 'lucide-react';

import { errorMessage } from '@/api-client/api-error';
import {
  useArchivePlaybook,
  useDeletePlaybook,
  useGetPlaybook,
  useListPendingPlaybookRevisions,
  useListPlaybooks,
  useRestorePlaybook,
  useSetPlaybookSharing,
} from '@/api-client/generated/playbooks/playbooks';
import type { PlaybookItem } from '@/api-client/model';
import { useConfirm } from '@/components/confirm-dialog';
import { EmptyState } from '@/components/empty-state';
import { Markdown } from '@/components/markdown';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { CATEGORY_LABEL } from '@/lib/labels';
import { dateTime } from '@/lib/utils/format';

import { useRecordParam } from '@/features/personal-data/hooks/use-record-param';

import { FINDING_LABEL, PLAYBOOK_STATUS, REVISION_STATUS, invalidatePlaybooks } from '../consts';
import { PlaybookEditor } from './playbook-editor';
import { DiffView, PlaybookProposalCard } from './playbook-proposal-card';

const categoryLabel = (value: string) => CATEGORY_LABEL[value as keyof typeof CATEGORY_LABEL] ?? value;

function PlaybookSheet({ playbookId, onClose }: { playbookId: number; onClose: () => void }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [editing, setEditing] = useState(false);
  const [compare, setCompare] = useState<number | null>(null);
  const detail = useGetPlaybook(playbookId);
  const options = { mutation: { onSuccess: () => invalidatePlaybooks(queryClient), onError: notify.error } };
  const sharing = useSetPlaybookSharing(options);
  const archive = useArchivePlaybook(options);
  const restore = useRestorePlaybook(options);
  const remove = useDeletePlaybook({ mutation: { onSuccess: () => invalidatePlaybooks(queryClient).then(onClose), onError: notify.error } });
  const playbook = detail.data;
  const active = playbook?.active_revision;
  const revisions = playbook?.revisions ?? [];
  const pending = revisions.filter(r => r.status === 'proposed');

  const onDelete = async () => {
    const ok = await confirm({
      title: '플레이북을 삭제할까요?',
      description:
        '모든 버전이 지워지고, 이 플레이북을 사용한 과거 답변은 근거가 삭제된 것으로 표시되어 이후 상담에 다시 보내지 않습니다. 대화 내용 자체는 남습니다. 잠시 쓰지 않으려면 보관하세요.',
      confirmLabel: '삭제',
      destructive: true,
    });
    if (ok) remove.mutate({ playbookId });
  };

  return (
    <Sheet open onOpenChange={open => !open && onClose()}>
      <SheetContent side='right' className='w-[min(640px,100%)] overflow-y-auto'>
        <SheetTitle>{active?.title ?? playbook?.slug ?? '플레이북'}</SheetTitle>
        <QueryStatus pending={detail.isPending} error={detail.error} retry={detail.refetch} label='플레이북' />
        {playbook && (
          <div className='mt-3 flex flex-col gap-4'>
            <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
              <Badge variant={playbook.status === 'active' ? 'success' : 'default'}>{PLAYBOOK_STATUS[playbook.status] ?? playbook.status}</Badge>
              <span>/{playbook.slug}</span>
              <span>상담에서 {playbook.usage_count}번 사용</span>
              {playbook.source === 'advisor' && <span>상담에서 배움</span>}
            </div>
            {active?.source_purged && (
              <Alert>학습 근거가 된 대화나 결정이 삭제되어 이 플레이북을 상담에 보내지 않습니다. 내용을 확인하고 수정해 저장하면 다시 사용합니다.</Alert>
            )}
            {active?.warnings.length ? (
              <Alert>확인할 내용: {active.warnings.map(w => FINDING_LABEL[w] ?? w).join(', ')}</Alert>
            ) : null}
            <label className='flex items-center gap-3'>
              <span className='flex-1'>
                <span className='block text-ui'>상담에 보내기</span>
                <span className='block text-2xs text-faint'>끄면 이 기기에만 두고 AI에는 보내지 않습니다.</span>
              </span>
              <Switch
                checked={playbook.external_allowed}
                disabled={sharing.isPending}
                onCheckedChange={value => sharing.mutate({ playbookId, data: { external_allowed: value } })}
              />
            </label>
            {active && (
              <div>
                <p className='text-ui text-muted-foreground'>{active.summary}</p>
                <div className='mt-1 flex flex-wrap gap-1'>
                  {active.categories.map(c => (
                    <Badge key={c}>{categoryLabel(c)}</Badge>
                  ))}
                  {active.triggers.map(t => (
                    <Badge key={t} variant='accent'>
                      {t}
                    </Badge>
                  ))}
                </div>
                <div className='mt-3 rounded-md border p-3'>
                  <Markdown text={active.body} />
                </div>
              </div>
            )}
            <div className='flex flex-wrap gap-2'>
              {active && (
                <Button size='sm' variant='primary' onClick={() => setEditing(true)}>
                  수정
                </Button>
              )}
              {playbook.status === 'archived' ? (
                <Button size='sm' disabled={restore.isPending} onClick={() => restore.mutate({ playbookId })}>
                  다시 사용
                </Button>
              ) : (
                <Button size='sm' disabled={archive.isPending} onClick={() => archive.mutate({ playbookId })}>
                  보관
                </Button>
              )}
              <Button size='sm' variant='ghost-destructive' disabled={remove.isPending} onClick={() => void onDelete()}>
                삭제
              </Button>
            </div>
            {pending.length > 0 && (
              <Section title='승인 대기 제안' count={pending.length}>
                <div className='flex flex-col gap-3'>
                  {pending.map(r => (
                    <PlaybookProposalCard key={r.id} revision={r} />
                  ))}
                </div>
              </Section>
            )}
            <Section title='수정 기록' count={revisions.length}>
              <ul className='divide-y'>
                {revisions.map(r => (
                  <li key={r.id} className='py-2'>
                    <div className='flex flex-wrap items-center gap-2 text-ui'>
                      <Badge variant={r.status === 'active' ? 'success' : 'default'}>{REVISION_STATUS[r.status] ?? r.status}</Badge>
                      <span>{r.title}</span>
                      <span className='text-2xs text-faint'>
                        {dateTime(r.decided_at ?? r.created_at)} · {r.source === 'advisor' ? '상담에서 제안' : '직접 작성'}
                      </span>
                      <Button size='sm' variant='ghost' className='ml-auto' aria-expanded={compare === r.id} onClick={() => setCompare(compare === r.id ? null : r.id)}>
                        {compare === r.id ? '접기' : '이전과 비교'}
                      </Button>
                    </div>
                    {compare === r.id && <DiffView revisionId={r.id} />}
                  </li>
                ))}
              </ul>
            </Section>
          </div>
        )}
        {editing && active && <PlaybookEditor open onClose={() => setEditing(false)} base={{ playbookId, revision: active }} />}
      </SheetContent>
    </Sheet>
  );
}

function PlaybookRow({ playbook, onOpen }: { playbook: PlaybookItem; onOpen: () => void }) {
  const active = playbook.active_revision;
  return (
    <li>
      <button type='button' onClick={onOpen} className='flex w-full flex-col gap-0.5 rounded-md px-2 py-2.5 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'>
        <span className='flex flex-wrap items-center gap-2'>
          <span className='font-medium'>{active?.title ?? playbook.slug}</span>
          <span className='text-2xs text-faint'>/{playbook.slug}</span>
          {playbook.status !== 'active' && <Badge>{PLAYBOOK_STATUS[playbook.status] ?? playbook.status}</Badge>}
          {!playbook.external_allowed && <Badge variant='warning'>이 기기에만</Badge>}
          {active?.source_purged && <Badge variant='warning'>근거가 삭제됨</Badge>}
          {(playbook.pending_count ?? 0) > 0 && <Badge variant='accent'>제안 {playbook.pending_count}건</Badge>}
        </span>
        {active && <span className='text-xs text-muted-foreground'>{active.summary}</span>}
        <span className='text-2xs text-faint'>
          {active?.categories.map(categoryLabel).join(' · ') || '영역 지정 없음'} · 상담에서 {playbook.usage_count}번 사용
        </span>
      </button>
    </li>
  );
}

/** Procedures the advisor follows; approved by the user, improved through reflection. */
export function PlaybooksView({ recordId }: { recordId: number | null }) {
  const [openId, setOpenId] = useRecordParam(recordId);
  const [creating, setCreating] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const playbooks = useListPlaybooks({ include_archived: showArchived });
  const pending = useListPendingPlaybookRevisions();
  const newOnes = pending.data?.filter(r => !r.base_revision_id) ?? [];

  return (
    <div className='max-w-[860px]'>
      {!!newOnes.length && (
        <Section title='새로 배운 절차' count={newOnes.length}>
          <div className='flex flex-col gap-3'>
            {newOnes.map(r => (
              <PlaybookProposalCard key={r.id} revision={r} />
            ))}
          </div>
        </Section>
      )}
      <Section
        title='플레이북'
        count={playbooks.data?.length}
        info={
          <p>
            상담할 때 따를 확인 순서입니다. 질문에 맞는 단어가 있거나 입력창에서 /짧은 이름 으로 부르면 최대 두 개를 함께 보냅니다. 상담에서 배운 절차는
            승인한 뒤에만 쓰며, 관련 영역의 공유를 막으면 보내지 않습니다.
          </p>
        }
        actions={
          <>
            <label className='flex items-center gap-1.5 text-xs text-muted-foreground'>
              <Switch checked={showArchived} onCheckedChange={setShowArchived} aria-label='보관한 플레이북도 보기' />
              보관함 포함
            </label>
            <Button size='sm' onClick={() => setCreating(true)}>
              <Plus /> 추가
            </Button>
          </>
        }>
        <QueryStatus pending={playbooks.isPending} error={playbooks.error} retry={playbooks.refetch} label='플레이북' rows={3} />
        {pending.error && <Alert variant='destructive'>{errorMessage(pending.error)}</Alert>}
        {playbooks.data?.length === 0 && (
          <EmptyState
            icon={BookOpenCheck}
            title='아직 플레이북이 없습니다'
            action={
              <Button size='sm' variant='primary' onClick={() => setCreating(true)}>
                직접 만들기
              </Button>
            }>
            상담 답변에서 ‘이 상담에서 배우기’를 누르면 다시 쓸 절차를 제안받을 수 있습니다.
          </EmptyState>
        )}
        <ul className='-mx-2'>
          {playbooks.data?.map(p => (
            <PlaybookRow key={p.id} playbook={p} onOpen={() => setOpenId(p.id)} />
          ))}
        </ul>
      </Section>
      {creating && <PlaybookEditor open onClose={() => setCreating(false)} />}
      {openId !== null && <PlaybookSheet playbookId={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}
