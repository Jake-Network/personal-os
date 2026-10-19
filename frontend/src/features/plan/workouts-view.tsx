'use client';

import { useMemo, useState } from 'react';

import { Dumbbell, Plus } from 'lucide-react';

import { TabToolbar } from '@/components/area-layout';
import { EmptyState } from '@/components/empty-state';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Button } from '@/components/ui/button';
import { dayLabel } from '@/lib/utils/format';
import { addDays, compareKeys, todayKey } from '@/lib/utils/zoned';

import { RecordSheet } from '@/features/personal-data/components/record-sheet';
import { useRecordParam } from '@/features/personal-data/hooks/use-record-param';
import { useResourceRows } from '@/features/personal-data/hooks/use-resource';
import { enumLabel } from '@/features/personal-data/consts/resources';

import { SourceCalendar } from './source-calendar';
import { useStoredView, ViewToggle } from './view-toggle';

/** Workout log with a four-week summary line. */
export function WorkoutsView({ recordId }: { recordId: number | null }) {
  const logs = useResourceRows('workout-logs');
  const [view, setView] = useStoredView('plan-workouts');
  const [selected, setSelected] = useRecordParam(recordId);
  const [creating, setCreating] = useState(false);
  const today = todayKey();

  const sorted = useMemo(() => [...(logs.data ?? [])].sort((a, b) => String(b.performed_on).localeCompare(String(a.performed_on))), [logs.data]);
  const recent = sorted.filter(l => compareKeys(String(l.performed_on), addDays(today, -28)) >= 0);
  const minutes = recent.reduce((sum, l) => sum + Number(l.duration_minutes ?? 0), 0);
  const editing = selected === null ? null : (logs.data?.find(l => l.id === selected) ?? null);

  return (
    <>
      <TabToolbar>
        <Button variant='primary' onClick={() => setCreating(true)}>
          <Plus /> 운동 기록
        </Button>
        {logs.data && logs.data.length > 0 && (
          <span className='text-ui text-muted-foreground'>
            최근 4주 {recent.length}회 · {minutes}분
          </span>
        )}
        <div className='ml-auto'>
          <ViewToggle value={view} onChange={setView} />
        </div>
      </TabToolbar>

      <QueryStatus pending={logs.isPending} error={logs.error} retry={logs.refetch} label='운동 기록' />

      {view === 'calendar' ? (
        <SourceCalendar sources={['workout-logs']} />
      ) : (
        logs.data && (
          <Section title='기록' count={sorted.length}>
            {sorted.length === 0 ? (
              <EmptyState
                icon={Dumbbell}
                title='운동 기록이 없습니다'
                action={
                  <Button variant='primary' size='sm' onClick={() => setCreating(true)}>
                    <Plus /> 기록 추가
                  </Button>
                }
              />
            ) : (
              <ul>
                {sorted.map(l => (
                  <li key={l.id} className='flex items-center gap-3 border-b py-2 last:border-b-0'>
                    <span className='w-28 shrink-0 text-xs text-faint'>{dayLabel(String(l.performed_on))}</span>
                    <button type='button' className='min-w-0 flex-1 text-left hover:underline' onClick={() => setSelected(l.id)}>
                      {String(l.activity)}
                    </button>
                    <span className='text-ui tabular-nums text-muted-foreground'>{String(l.duration_minutes)}분</span>
                    {l.intensity ? <span className='w-12 text-right text-xs text-faint'>{enumLabel(l.intensity)}</span> : <span className='w-12' />}
                  </li>
                ))}
              </ul>
            )}
          </Section>
        )
      )}

      <RecordSheet
        resource='workout-logs'
        record={creating ? null : editing}
        open={creating || editing !== null}
        defaults={creating ? { performed_on: today } : undefined}
        onClose={() => {
          setCreating(false);
          setSelected(null);
        }}
      />
    </>
  );
}
