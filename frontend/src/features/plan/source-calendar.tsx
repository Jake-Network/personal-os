'use client';

import { useState } from 'react';

import { CalendarView, TONE_CLASS } from '@/components/calendar/calendar-view';
import type { CalendarItem, CalendarSelection } from '@/components/calendar/calendar-utils';
import { QueryStatus } from '@/components/query-status';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { dayLabel, timeOnly } from '@/lib/utils/format';
import { cn } from '@/lib/utils';
import { todayKey, zonedInstant } from '@/lib/utils/zoned';

import type { Row } from '@/features/personal-data/api/resource-api';
import { RecordSheet } from '@/features/personal-data/components/record-sheet';
import { useResourceRows } from '@/features/personal-data/hooks/use-resource';

import { itemRef, SOURCES, type SourceId } from './calendar-sources';

function selectionText(s: CalendarSelection): string {
  if (s.kind === 'time') return `${dayLabel(s.day)} ${timeOnly(zonedInstant(s.day, s.startMinute))}–${timeOnly(zonedInstant(s.day, s.endMinute))}`;
  return s.start === s.end ? dayLabel(s.start) : `${dayLabel(s.start)} – ${dayLabel(s.end)}`;
}

/** Rows of all the given sources, loaded together; an unused source is not fetched. */
function useSourceRows(ids: SourceId[]) {
  const has = (id: SourceId) => ids.includes(id);
  const events = useResourceRows('calendar-events', has('calendar-events'));
  const interviews = useResourceRows('interviews', has('interviews'));
  const applications = useResourceRows('job-applications', has('interviews'));
  const tasks = useResourceRows('tasks', has('tasks'));
  const goals = useResourceRows('goals', has('goals'));
  const expenses = useResourceRows('planned-expenses', has('planned-expenses'));
  const workouts = useResourceRows('workout-logs', has('workout-logs'));
  const queries: Record<SourceId, typeof events> = {
    'calendar-events': events,
    interviews,
    tasks,
    goals,
    'planned-expenses': expenses,
    'workout-logs': workouts,
  };
  return { queries, applications };
}

interface Props {
  sources: SourceId[];
  /** Show a toggle per source (the combined calendar). */
  layers?: boolean;
}

/** A calendar over personal records: pick days or a time to add one, click an entry to edit it. */
export function SourceCalendar({ sources, layers = false }: Props) {
  const { queries, applications } = useSourceRows(sources);
  const [hidden, setHidden] = useState<Set<SourceId>>(new Set());
  const [selection, setSelection] = useState<CalendarSelection | null>(null);
  const [adding, setAdding] = useState<{ source: SourceId; selection: CalendarSelection } | null>(null);
  const [editing, setEditing] = useState<{ source: SourceId; row: Row } | null>(null);
  const shown = sources.filter(s => !hidden.has(s));
  const today = todayKey();

  const appMap = new Map((applications.data ?? []).map(a => [a.id, a]));
  const items: CalendarItem[] = shown.flatMap(id => SOURCES[id].toItems(queries[id].data ?? [], { today, applications: appMap }));
  const failed = sources.map(id => queries[id]).find(q => q.error);
  const pending = sources.some(id => queries[id].isPending);

  const pick = (s: CalendarSelection) => {
    if (sources.length === 1) setAdding({ source: sources[0], selection: s });
    else setSelection(s);
  };
  const open = (item: CalendarItem) => {
    const { source, id } = itemRef(item.key);
    const row = queries[source].data?.find(r => r.id === id);
    if (row) setEditing({ source, row });
  };
  const add = adding ? SOURCES[adding.source].defaults(adding.selection) : null;

  return (
    <>
      {failed && <QueryStatus pending={false} error={failed.error} retry={failed.refetch} label='달력' />}
      <CalendarView
        items={items}
        onSelect={pick}
        onOpenItem={open}
        allowTime={sources.some(s => SOURCES[s].timed)}
        className={cn(pending && 'opacity-70')}
        toolbar={
          layers && (
            <div className='flex flex-wrap gap-1' role='group' aria-label='표시할 항목'>
              {sources.map(id => {
                const on = !hidden.has(id);
                return (
                  <button
                    key={id}
                    type='button'
                    aria-pressed={on}
                    onClick={() =>
                      setHidden(prev => {
                        const next = new Set(prev);
                        if (on) next.add(id);
                        else next.delete(id);
                        return next;
                      })
                    }
                    className={cn(
                      'inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs',
                      on ? 'border-transparent' : 'text-faint line-through',
                      on && TONE_CLASS[SOURCES[id].tone],
                    )}>
                    {SOURCES[id].label}
                  </button>
                );
              })}
            </div>
          )
        }
      />

      <Dialog open={!!selection} onOpenChange={o => !o && setSelection(null)}>
        <DialogContent className='w-[min(380px,calc(100%-32px))]'>
          <DialogHeader>
            <DialogTitle>무엇을 추가할까요?</DialogTitle>
            {selection && <p className='text-ui text-muted-foreground'>{selectionText(selection)}</p>}
          </DialogHeader>
          <div className='grid grid-cols-2 gap-2'>
            {sources.map(id => (
              <Button
                key={id}
                className='h-10 justify-start'
                onClick={() => {
                  setAdding({ source: id, selection: selection! });
                  setSelection(null);
                }}>
                <span className={cn('size-2.5 rounded-full', TONE_CLASS[SOURCES[id].tone])} aria-hidden />
                {SOURCES[id].label}
              </Button>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      {adding && add && (
        <RecordSheet
          resource={adding.source}
          record={null}
          open
          defaults={add.values}
          note={[selectionText(adding.selection), add.note].filter(Boolean).join(' · ')}
          onClose={() => setAdding(null)}
        />
      )}
      {editing && <RecordSheet resource={editing.source} record={editing.row} open onClose={() => setEditing(null)} />}
    </>
  );
}
