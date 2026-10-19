'use client';

import { useMemo, useState } from 'react';

import { Plus, Target } from 'lucide-react';

import { TabToolbar } from '@/components/area-layout';
import { EmptyState } from '@/components/empty-state';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { StatusBadge } from '@/components/status-badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { dateOnly } from '@/lib/utils/format';
import { cn } from '@/lib/utils';
import { compareKeys, todayKey } from '@/lib/utils/zoned';

import type { Row } from '@/features/personal-data/api/resource-api';
import { RecordSheet } from '@/features/personal-data/components/record-sheet';
import { useRecordParam } from '@/features/personal-data/hooks/use-record-param';
import { useResourceRows } from '@/features/personal-data/hooks/use-resource';
import { enumLabel } from '@/features/personal-data/consts/resources';

import { SourceCalendar } from './source-calendar';
import { TaskRow } from './tasks-view';
import { useStoredView, ViewToggle } from './view-toggle';

function daysLeft(target: string, today: string): string {
  const diff = Math.round((Date.parse(`${target}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
  if (diff === 0) return '오늘까지';
  return diff > 0 ? `D-${diff}` : `${-diff}일 지남`;
}

/** Progress is shown as recorded (free text such as "3권" or "70kg"); nothing is computed from it. */
function progressText(goal: Row): string | null {
  const unit = goal.unit ? ` ${goal.unit}` : '';
  if (goal.current_value && goal.target_value) return `${goal.current_value} / ${goal.target_value}${unit}`;
  if (goal.target_value) return `목표 ${goal.target_value}${unit}`;
  if (goal.current_value) return `현재 ${goal.current_value}${unit}`;
  return null;
}

function GoalCard({ goal, tasks, today, onOpen, onAddTask, onOpenTask }: { goal: Row; tasks: Row[]; today: string; onOpen: () => void; onAddTask: () => void; onOpenTask: (t: Row) => void }) {
  const open = tasks.filter(t => t.status !== 'done');
  const target = typeof goal.target_date === 'string' ? goal.target_date : null;
  const progress = progressText(goal);
  return (
    <Card className='flex flex-col gap-2 p-4'>
      <div className='flex items-start gap-2'>
        <button type='button' onClick={onOpen} className='min-w-0 flex-1 text-left text-title font-semibold hover:underline'>
          {String(goal.title)}
        </button>
        {goal.status !== 'active' && <StatusBadge value={String(goal.status)} />}
      </div>
      <div className='flex flex-wrap items-center gap-x-2 text-xs text-faint'>
        <span>{enumLabel(goal.category)}</span>
        <span>{enumLabel(goal.horizon)}</span>
        {target && (
          <span className={cn(goal.status === 'active' && compareKeys(target, today) < 0 && 'text-destructive')}>
            {dateOnly(target)} · {daysLeft(target, today)}
          </span>
        )}
      </div>
      {progress && <p className='text-ui tabular-nums'>{progress}</p>}
      <div className='mt-1 border-t pt-2'>
        <div className='mb-1 flex items-center justify-between text-xs text-muted-foreground'>
          <span>{open.length ? `남은 할 일 ${open.length}개` : tasks.length ? '연결된 할 일을 모두 마쳤습니다' : '연결된 할 일 없음'}</span>
          <Button size='sm' variant='ghost' onClick={onAddTask}>
            <Plus /> 할 일
          </Button>
        </div>
        {open.length > 0 && (
          <ul>
            {open.slice(0, 3).map(t => (
              <TaskRow key={t.id} task={t} today={today} onOpen={() => onOpenTask(t)} />
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

/** Goals with their recorded progress and the tasks that move them forward. */
export function GoalsView({ recordId }: { recordId: number | null }) {
  const goals = useResourceRows('goals');
  const tasks = useResourceRows('tasks');
  const [view, setView] = useStoredView('plan-goals');
  const [selected, setSelected] = useRecordParam(recordId);
  const [creating, setCreating] = useState(false);
  const [taskSheet, setTaskSheet] = useState<{ task: Row | null; goalId?: number } | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  const today = todayKey();

  const byGoal = useMemo(() => {
    const map = new Map<number, Row[]>();
    for (const t of tasks.data ?? []) if (typeof t.goal_id === 'number') map.set(t.goal_id, [...(map.get(t.goal_id) ?? []), t]);
    return map;
  }, [tasks.data]);
  const active = (goals.data ?? []).filter(g => g.status === 'active');
  const closed = (goals.data ?? []).filter(g => g.status !== 'active');
  const editing = selected === null ? null : (goals.data?.find(g => g.id === selected) ?? null);

  const cards = (list: Row[]) => (
    <div className='grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3'>
      {list.map(g => (
        <GoalCard
          key={g.id}
          goal={g}
          tasks={byGoal.get(g.id) ?? []}
          today={today}
          onOpen={() => setSelected(g.id)}
          onAddTask={() => setTaskSheet({ task: null, goalId: g.id })}
          onOpenTask={t => setTaskSheet({ task: t })}
        />
      ))}
    </div>
  );

  return (
    <>
      <TabToolbar>
        <Button variant='primary' onClick={() => setCreating(true)}>
          <Plus /> 목표
        </Button>
        <div className='ml-auto'>
          <ViewToggle value={view} onChange={setView} />
        </div>
      </TabToolbar>

      <QueryStatus pending={goals.isPending} error={goals.error ?? tasks.error} retry={() => Promise.all([goals.refetch(), tasks.refetch()])} label='목표' />

      {view === 'calendar' ? (
        <SourceCalendar sources={['goals', 'tasks']} layers />
      ) : (
        goals.data && (
          <>
            {goals.data.length === 0 && (
              <EmptyState
                icon={Target}
                title='목표가 없습니다'
                action={
                  <Button variant='primary' size='sm' onClick={() => setCreating(true)}>
                    <Plus /> 목표 추가
                  </Button>
                }>
                목표에 할 일을 연결하면 진행 상황을 함께 볼 수 있습니다.
              </EmptyState>
            )}
            {active.length > 0 && (
              <Section title='진행 중' count={active.length}>
                {cards(active)}
              </Section>
            )}
            {closed.length > 0 && (
              <Section
                title='완료·중단'
                count={closed.length}
                actions={
                  <Button size='sm' variant='ghost' aria-expanded={showClosed} onClick={() => setShowClosed(v => !v)}>
                    {showClosed ? '접기' : '보기'}
                  </Button>
                }>
                {showClosed && cards(closed)}
              </Section>
            )}
          </>
        )
      )}

      <RecordSheet
        resource='goals'
        record={creating ? null : editing}
        open={creating || editing !== null}
        onClose={() => {
          setCreating(false);
          setSelected(null);
        }}
      />
      {taskSheet && (
        <RecordSheet
          resource='tasks'
          record={taskSheet.task}
          open
          defaults={taskSheet.goalId ? { goal_id: taskSheet.goalId } : undefined}
          onClose={() => setTaskSheet(null)}
        />
      )}
    </>
  );
}
