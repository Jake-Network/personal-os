'use client';

import { useMemo, useState } from 'react';

import Link from 'next/link';

import { ListChecks, Plus } from 'lucide-react';

import { TabToolbar } from '@/components/area-layout';
import { EmptyState } from '@/components/empty-state';
import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { dateOnly } from '@/lib/utils/format';
import { cn } from '@/lib/utils';
import { addDays, compareKeys, todayKey } from '@/lib/utils/zoned';

import type { Row } from '@/features/personal-data/api/resource-api';
import { RecordSheet } from '@/features/personal-data/components/record-sheet';
import { recordHref, useRecordParam } from '@/features/personal-data/hooks/use-record-param';
import { useResourceRows, useUpdateRow } from '@/features/personal-data/hooks/use-resource';

import { SourceCalendar } from './source-calendar';
import { useStoredView, ViewToggle } from './view-toggle';

type Group = 'overdue' | 'today' | 'week' | 'later' | 'undated' | 'done';

const GROUP_LABEL: Record<Group, string> = {
  overdue: '지연',
  today: '오늘',
  week: '이번 주',
  later: '나중에',
  undated: '날짜 없음',
  done: '완료',
};

export function groupOf(task: Row, today: string): Group {
  if (task.status === 'done') return 'done';
  const due = typeof task.due_on === 'string' ? task.due_on : null;
  if (!due) return 'undated';
  if (compareKeys(due, today) < 0) return 'overdue';
  if (due === today) return 'today';
  if (compareKeys(due, addDays(today, 7)) < 0) return 'week';
  return 'later';
}

function dueText(due: string, today: string): string {
  if (due === today) return '오늘';
  if (due === addDays(today, 1)) return '내일';
  const diff = Math.round((Date.parse(`${due}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
  if (diff < 0) return `${-diff}일 지남`;
  if (diff < 7) return `${diff}일 후`;
  return dateOnly(due);
}

export function TaskRow({ task, today, goal, onOpen }: { task: Row; today: string; goal?: Row; onOpen: () => void }) {
  const update = useUpdateRow('tasks');
  const done = task.status === 'done';
  const due = typeof task.due_on === 'string' ? task.due_on : null;
  const pendingDone = update.isPending ? update.variables?.changes.status === 'done' : done;

  return (
    <li className='flex items-start gap-3 border-b py-2 last:border-b-0'>
      <Checkbox
        className='mt-0.5'
        checked={pendingDone}
        disabled={update.isPending}
        aria-label={`${task.title} ${done ? '완료 취소' : '완료'}`}
        onCheckedChange={v =>
          update.mutate({ row: task, changes: { status: v === true ? 'done' : 'todo' } }, { onError: e => notify.error(e) })
        }
      />
      <div className='min-w-0 flex-1'>
        <button
          type='button'
          onClick={onOpen}
          className={cn('text-left hover:underline', pendingDone && 'text-faint line-through')}>
          {String(task.title)}
        </button>
        <div className='flex flex-wrap items-center gap-x-2 text-xs text-faint'>
          {task.status === 'doing' && <span className='text-accent-foreground'>진행 중</span>}
          {goal && (
            <Link href={recordHref('/plan/goals', goal.id)} className='hover:underline'>
              목표 · {String(goal.title)}
            </Link>
          )}
          {typeof task.estimate_minutes === 'number' && <span>{task.estimate_minutes}분 예상</span>}
        </div>
      </div>
      {task.priority === 'high' && !done && <Badge variant='warning'>중요</Badge>}
      {due && <span className={cn('shrink-0 text-xs tabular-nums', groupOf(task, today) === 'overdue' ? 'text-destructive' : 'text-faint')}>{dueText(due, today)}</span>}
    </li>
  );
}

/** Open work grouped by when it is due; check a box to finish it. */
export function TasksView({ recordId }: { recordId: number | null }) {
  const tasks = useResourceRows('tasks');
  const goals = useResourceRows('goals');
  const [view, setView] = useStoredView('plan-tasks');
  const [selected, setSelected] = useRecordParam(recordId);
  const [creating, setCreating] = useState(false);
  const [showDone, setShowDone] = useState(false);
  const today = todayKey();

  const goalMap = useMemo(() => new Map((goals.data ?? []).map(g => [g.id, g])), [goals.data]);
  const groups = useMemo(() => {
    const out = new Map<Group, Row[]>();
    for (const t of tasks.data ?? []) {
      const g = groupOf(t, today);
      out.set(g, [...(out.get(g) ?? []), t]);
    }
    for (const list of out.values()) list.sort((a, b) => String(a.due_on ?? '9999').localeCompare(String(b.due_on ?? '9999')) || Number(b.priority === 'high') - Number(a.priority === 'high'));
    return out;
  }, [tasks.data, today]);
  const editing = selected === null ? null : (tasks.data?.find(t => t.id === selected) ?? null);
  const open = (tasks.data ?? []).filter(t => t.status !== 'done').length;

  return (
    <>
      <TabToolbar>
        <Button variant='primary' onClick={() => setCreating(true)}>
          <Plus /> 할 일
        </Button>
        <span className='text-ui text-muted-foreground'>{tasks.data ? `남은 일 ${open}개` : ''}</span>
        <div className='ml-auto'>
          <ViewToggle value={view} onChange={setView} />
        </div>
      </TabToolbar>

      <QueryStatus pending={tasks.isPending} error={tasks.error} retry={tasks.refetch} label='할 일' />

      {view === 'calendar' ? (
        <SourceCalendar sources={['tasks']} />
      ) : (
        tasks.data && (
          <>
            {tasks.data.length === 0 && (
              <EmptyState
                icon={ListChecks}
                title='할 일이 없습니다'
                action={
                  <Button variant='primary' size='sm' onClick={() => setCreating(true)}>
                    <Plus /> 할 일 추가
                  </Button>
                }>
                마감일을 넣으면 달력과 홈에도 나타납니다.
              </EmptyState>
            )}
            {(['overdue', 'today', 'week', 'later', 'undated'] as Group[]).map(g => {
              const list = groups.get(g);
              if (!list?.length) return null;
              return (
                <Section key={g} title={<span className={cn(g === 'overdue' && 'text-destructive')}>{GROUP_LABEL[g]}</span>} count={list.length}>
                  <ul>
                    {list.map(t => (
                      <TaskRow key={t.id} task={t} today={today} goal={typeof t.goal_id === 'number' ? goalMap.get(t.goal_id) : undefined} onOpen={() => setSelected(t.id)} />
                    ))}
                  </ul>
                </Section>
              );
            })}
            {!!groups.get('done')?.length && (
              <Section
                title={GROUP_LABEL.done}
                count={groups.get('done')!.length}
                actions={
                  <Button size='sm' variant='ghost' aria-expanded={showDone} onClick={() => setShowDone(v => !v)}>
                    {showDone ? '접기' : '보기'}
                  </Button>
                }>
                {showDone && (
                  <ul>
                    {groups.get('done')!.map(t => (
                      <TaskRow key={t.id} task={t} today={today} goal={typeof t.goal_id === 'number' ? goalMap.get(t.goal_id) : undefined} onOpen={() => setSelected(t.id)} />
                    ))}
                  </ul>
                )}
              </Section>
            )}
          </>
        )
      )}

      <RecordSheet
        resource='tasks'
        record={creating ? null : editing}
        open={creating || editing !== null}
        onClose={() => {
          setCreating(false);
          setSelected(null);
        }}
      />
    </>
  );
}
