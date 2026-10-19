'use client';

import { useMemo, useState } from 'react';

import { CalendarDays, MapPin, Plus, TriangleAlert } from 'lucide-react';

import { TabToolbar } from '@/components/area-layout';
import { conflictingKeys, itemSpan, sortItems } from '@/components/calendar/calendar-utils';
import { EmptyState } from '@/components/empty-state';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { StatusBadge } from '@/components/status-badge';
import { Button } from '@/components/ui/button';
import { dayLabel, timeOnly } from '@/lib/utils/format';
import { addDays, compareKeys, todayKey } from '@/lib/utils/zoned';

import { RecordSheet } from '@/features/personal-data/components/record-sheet';
import { useRecordParam } from '@/features/personal-data/hooks/use-record-param';
import { useResourceRows } from '@/features/personal-data/hooks/use-resource';

import { itemRef, SOURCES } from './calendar-sources';
import { SourceCalendar } from './source-calendar';
import { useStoredView, ViewToggle } from './view-toggle';

/** Upcoming events day by day, or the calendar; pick days or a time there to add one. */
export function EventsView({ recordId }: { recordId: number | null }) {
  const events = useResourceRows('calendar-events');
  const [view, setView] = useStoredView('plan-events', 'calendar');
  const [selected, setSelected] = useRecordParam(recordId);
  const [creating, setCreating] = useState(false);
  const [showPast, setShowPast] = useState(false);
  const today = todayKey();

  const items = useMemo(() => sortItems(SOURCES['calendar-events'].toItems(events.data ?? [], { today })), [events.data, today]);
  const days = useMemo(() => {
    const byDay = new Map<string, typeof items>();
    for (const item of items) {
      const [first, last] = itemSpan(item);
      // A multi-day event is listed on each of its days from today on.
      for (let d = compareKeys(first, today) < 0 && !showPast ? today : first; compareKeys(d, last) <= 0; d = addDays(d, 1)) {
        if (!showPast && compareKeys(d, today) < 0) continue;
        byDay.set(d, [...(byDay.get(d) ?? []), item]);
        if (byDay.size > 400) break;
      }
    }
    return [...byDay.entries()].sort(([a], [b]) => (showPast ? compareKeys(b, a) : compareKeys(a, b)));
  }, [items, today, showPast]);
  const conflicts = useMemo(() => conflictingKeys(items, days.map(([d]) => d)), [items, days]);
  const editing = selected === null ? null : (events.data?.find(e => e.id === selected) ?? null);

  return (
    <>
      <TabToolbar>
        <Button variant='primary' onClick={() => setCreating(true)}>
          <Plus /> 일정
        </Button>
        <div className='ml-auto'>
          <ViewToggle value={view} onChange={setView} />
        </div>
      </TabToolbar>

      <QueryStatus pending={events.isPending} error={events.error} retry={events.refetch} label='일정' />

      {view === 'calendar' ? (
        <SourceCalendar sources={['calendar-events']} />
      ) : (
        events.data && (
          <>
            <div className='mb-3 flex justify-end'>
              <Button size='sm' variant='ghost' aria-pressed={showPast} onClick={() => setShowPast(v => !v)}>
                {showPast ? '다가오는 일정 보기' : '지난 일정 보기'}
              </Button>
            </div>
            {days.length === 0 && (
              <EmptyState
                icon={CalendarDays}
                title={showPast ? '지난 일정이 없습니다' : '다가오는 일정이 없습니다'}
                action={
                  <Button variant='primary' size='sm' onClick={() => setCreating(true)}>
                    <Plus /> 일정 추가
                  </Button>
                }>
                달력에서 날짜를 누르거나 여러 날을 끌어서 추가할 수도 있습니다.
              </EmptyState>
            )}
            {days.map(([day, list]) => (
              <Section key={day} title={<span className={day === today ? 'text-primary' : undefined}>{dayLabel(day)}{day === today ? ' · 오늘' : ''}</span>}>
                <ul>
                  {list.map(item => {
                    const row = events.data!.find(e => e.id === itemRef(item.key).id)!;
                    return (
                      <li key={item.key} className='flex items-start gap-3 border-b py-2 last:border-b-0'>
                        <span className='w-28 shrink-0 text-xs tabular-nums text-muted-foreground'>
                          {item.allDay ? '종일' : `${timeOnly(item.start)}${item.end ? ` – ${timeOnly(item.end)}` : ''}`}
                        </span>
                        <div className='min-w-0 flex-1'>
                          <button type='button' className='text-left font-medium hover:underline' onClick={() => setSelected(row.id)}>
                            {item.title}
                          </button>
                          {item.detail && (
                            <div className='flex items-center gap-1 text-xs text-faint'>
                              <MapPin className='size-3' aria-hidden /> {item.detail}
                            </div>
                          )}
                        </div>
                        {conflicts.has(item.key) && (
                          <span className='inline-flex items-center gap-1 text-xs text-warning'>
                            <TriangleAlert className='size-3' aria-hidden /> 겹침
                          </span>
                        )}
                        <StatusBadge value={String(row.kind)} tone={row.kind === 'interview' ? 'accent' : 'default'} />
                      </li>
                    );
                  })}
                </ul>
              </Section>
            ))}
          </>
        )
      )}

      <RecordSheet
        resource='calendar-events'
        record={creating ? null : editing}
        open={creating || editing !== null}
        defaults={creating ? SOURCES['calendar-events'].defaults({ kind: 'time', day: today, startMinute: 9 * 60, endMinute: 10 * 60 }).values : undefined}
        onClose={() => {
          setCreating(false);
          setSelected(null);
        }}
      />
    </>
  );
}
