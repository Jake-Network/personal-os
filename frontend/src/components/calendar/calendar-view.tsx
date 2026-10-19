'use client';

import { type KeyboardEvent, type PointerEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react';

import { ChevronLeft, ChevronRight, Plus, TriangleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { dayLabel, displayTimeZone, timeOnly } from '@/lib/utils/format';
import { cn } from '@/lib/utils';
import { addDays, compareKeys, todayKey } from '@/lib/utils/zoned';

import {
  type CalendarItem,
  type CalendarSelection,
  type CalendarTone,
  conflictingKeys,
  coversDay,
  layoutDay,
  monthMatrix,
  normalizeDays,
  shiftMonth,
  sortItems,
  weekDays,
} from './calendar-utils';

export type { CalendarItem, CalendarSelection, CalendarTone } from './calendar-utils';

const WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일'];
const SLOT = 30; // minutes per week-grid row
const SLOT_PX = 22;
const MAX_IN_CELL = 3;

export const TONE_CLASS: Record<CalendarTone, string> = {
  event: 'bg-accent text-accent-foreground',
  interview: 'bg-info-soft text-foreground',
  task: 'bg-muted text-foreground',
  goal: 'bg-success-soft text-success',
  expense: 'bg-warning-soft text-warning',
  workout: 'bg-secondary text-muted-foreground',
};

export const TONE_LABEL: Record<CalendarTone, string> = {
  event: '일정',
  interview: '면접',
  task: '할 일',
  goal: '목표',
  expense: '예정 지출',
  workout: '운동',
};

interface Props {
  items: CalendarItem[];
  /** Called with the picked day(s) or time range; the caller opens the matching form. */
  onSelect: (selection: CalendarSelection) => void;
  onOpenItem: (item: CalendarItem) => void;
  /** Week view with time slots, for sources that have a time of day. */
  allowTime?: boolean;
  /** Extra controls in the header, e.g. layer toggles. */
  toolbar?: ReactNode;
  className?: string;
}

function ItemChip({ item, conflict, onOpen, compact }: { item: CalendarItem; conflict?: boolean; onOpen: () => void; compact?: boolean }) {
  return (
    <button
      type='button'
      data-calendar-item
      onPointerDown={e => e.stopPropagation()}
      onClick={e => {
        e.stopPropagation();
        onOpen();
      }}
      title={`${TONE_LABEL[item.tone]} · ${item.title}${item.detail ? ` · ${item.detail}` : ''}`}
      className={cn(
        'flex w-full min-w-0 items-center gap-1 truncate rounded-sm px-1.5 text-left text-2xs leading-5 hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        TONE_CLASS[item.tone],
        item.done && 'line-through opacity-60',
        item.overdue && 'ring-1 ring-destructive',
        conflict && 'ring-1 ring-warning',
      )}>
      {conflict && <TriangleAlert className='size-3 shrink-0' aria-label='겹치는 일정' />}
      {!item.allDay && !compact && !/^\d{4}-\d{2}-\d{2}$/.test(item.start) && (
        <span className='shrink-0 tabular-nums opacity-80'>{timeOnly(item.start)}</span>
      )}
      <span className='truncate'>{item.title}</span>
    </button>
  );
}

function inRange(day: string, range: { start: string; end: string } | null) {
  return !!range && compareKeys(range.start, day) <= 0 && compareKeys(day, range.end) <= 0;
}

/** Month and week calendar; click a day, drag across days, or drag over time slots to add something there. */
export function CalendarView({ items, onSelect, onOpenItem, allowTime = false, toolbar, className }: Props) {
  const tz = displayTimeZone();
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const today = todayKey(tz);
  const [view, setView] = useState<'month' | 'week'>('month');
  const [anchor, setAnchor] = useState(today);
  const [focusDay, setFocusDay] = useState(today);
  const [dayRange, setDayRange] = useState<{ start: string; end: string } | null>(null);
  const dragAnchor = useRef<string | null>(null);
  const [timeDrag, setTimeDrag] = useState<{ day: string; from: number; to: number } | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const weekScroll = useRef<HTMLDivElement>(null);

  const sorted = useMemo(() => sortItems(items), [items]);
  const weeks = useMemo(() => monthMatrix(anchor), [anchor]);
  const week = useMemo(() => weekDays(anchor), [anchor]);
  const visibleDays = view === 'month' ? weeks.flat() : week;
  const conflicts = useMemo(() => conflictingKeys(sorted, visibleDays, tz), [sorted, visibleDays, tz]);
  const month = anchor.slice(0, 7);

  useEffect(() => {
    if (view === 'week' && weekScroll.current) weekScroll.current.scrollTop = ((8 * 60) / SLOT) * SLOT_PX;
  }, [view]);

  useEffect(() => {
    // A drag can end outside the grid.
    const up = () => {
      if (dragAnchor.current && dayRange) onSelect({ kind: 'days', ...dayRange });
      dragAnchor.current = null;
      setDayRange(null);
    };
    window.addEventListener('pointerup', up);
    return () => window.removeEventListener('pointerup', up);
  }, [dayRange, onSelect]);

  const move = (days: number) => {
    const next = view === 'month' ? shiftMonth(anchor, days > 0 ? 1 : -1) : addDays(anchor, days > 0 ? 7 : -7);
    setAnchor(next);
    setFocusDay(view === 'month' ? next : addDays(focusDay, days > 0 ? 7 : -7));
  };

  const title =
    view === 'month'
      ? `${Number(month.slice(0, 4))}년 ${Number(month.slice(5, 7))}월`
      : `${dayLabel(week[0]).replace(/ \(.\)$/, '')} – ${dayLabel(week[6]).replace(/ \(.\)$/, '')}`;

  const focusCell = (day: string) => {
    setFocusDay(day);
    if (day.slice(0, 7) !== anchor.slice(0, 7) && view === 'month') setAnchor(`${day.slice(0, 7)}-01`);
    if (view === 'week' && !week.includes(day)) setAnchor(day);
    requestAnimationFrame(() => gridRef.current?.querySelector<HTMLElement>(`[data-day="${day}"]`)?.focus());
  };

  const keyNav = (e: KeyboardEvent<HTMLDivElement>, day: string) => {
    const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (delta !== undefined) {
      e.preventDefault();
      const next = addDays(day, delta);
      if (e.shiftKey) setDayRange(normalizeDays(dayRange ? (dayRange.start === day ? dayRange.end : dayRange.start) : day, next));
      else setDayRange(null);
      focusCell(next);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect({ kind: 'days', ...(dayRange && inRange(day, dayRange) ? dayRange : { start: day, end: day }) });
      setDayRange(null);
    } else if (e.key === 'Escape') setDayRange(null);
  };

  const dayCellProps = (day: string) => ({
    'data-day': day,
    role: 'gridcell',
    tabIndex: day === focusDay ? 0 : -1,
    'aria-selected': inRange(day, dayRange),
    'aria-label': `${dayLabel(day)}${day === today ? ', 오늘' : ''}`,
    onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => {
      // Item buttons keep their native Enter/Space activation and arrow-key behavior.
      if (e.target === e.currentTarget) keyNav(e, day);
    },
    onFocus: () => setFocusDay(day),
    onPointerDown: (e: PointerEvent<HTMLDivElement>) => {
      if (e.button !== 0) return;
      if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
      dragAnchor.current = day;
      setDayRange({ start: day, end: day });
    },
    onPointerEnter: () => {
      if (dragAnchor.current) setDayRange(normalizeDays(dragAnchor.current, day));
    },
  });

  const allDayItems = (day: string) => sorted.filter(i => (i.allDay || /^\d{4}-\d{2}-\d{2}$/.test(i.start)) && coversDay(i, day, tz));

  const finishTimeDrag = () => {
    if (!timeDrag) return;
    const from = Math.min(timeDrag.from, timeDrag.to);
    const to = Math.max(timeDrag.from, timeDrag.to) + SLOT;
    onSelect({ kind: 'time', day: timeDrag.day, startMinute: from, endMinute: to });
    setTimeDrag(null);
  };

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <div className='flex flex-wrap items-center gap-2'>
        <div className='flex items-center gap-1'>
          <Button size='icon-sm' variant='ghost' aria-label={view === 'month' ? '이전 달' : '이전 주'} onClick={() => move(-1)}>
            <ChevronLeft />
          </Button>
          <Button size='icon-sm' variant='ghost' aria-label={view === 'month' ? '다음 달' : '다음 주'} onClick={() => move(1)}>
            <ChevronRight />
          </Button>
          <Button
            size='sm'
            onClick={() => {
              setAnchor(today);
              setFocusDay(today);
            }}>
            오늘
          </Button>
        </div>
        <h2 className='text-title font-semibold' aria-live='polite'>
          {title}
        </h2>
        {tz !== browserTz && <span className='text-xs text-faint'>{tz} 기준</span>}
        <div className='ml-auto flex flex-wrap items-center gap-2'>
          {toolbar}
          {allowTime && (
            <div className='hidden rounded-md bg-muted p-0.5 md:inline-flex' role='group' aria-label='보기'>
              {(['month', 'week'] as const).map(v => (
                <button
                  key={v}
                  type='button'
                  aria-pressed={view === v}
                  onClick={() => setView(v)}
                  className={cn('h-7 rounded-sm px-3 text-ui text-muted-foreground', view === v && 'bg-card font-medium text-foreground shadow-sm')}>
                  {v === 'month' ? '월' : '주'}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Wide screens: month or week grid. */}
      <div ref={gridRef} className='hidden select-none md:block'>
        {view === 'month' ? (
          <div role='grid' aria-label={`${title} 달력. 날짜를 누르거나 여러 날을 끌어서 추가`} className='overflow-hidden rounded-lg border bg-card'>
            <div role='row' className='grid grid-cols-7 border-b bg-muted/50'>
              {WEEKDAYS.map((w, i) => (
                <div key={w} role='columnheader' className={cn('px-2 py-1 text-xs text-faint', i >= 5 && 'text-destructive/70')}>
                  {w}
                </div>
              ))}
            </div>
            {weeks.map(days => (
              <div key={days[0]} role='row' className='grid grid-cols-7 border-b last:border-b-0'>
                {days.map(day => {
                  const dayItems = sorted.filter(i => coversDay(i, day, tz));
                  const outside = day.slice(0, 7) !== month;
                  return (
                    <div
                      key={day}
                      {...dayCellProps(day)}
                      className={cn(
                        'group relative flex min-h-24 cursor-pointer flex-col gap-0.5 border-r p-1 outline-none last:border-r-0 hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                        outside && 'bg-muted/30 text-faint',
                        inRange(day, dayRange) && 'bg-accent/70 hover:bg-accent/70',
                      )}>
                      <div className='flex items-center justify-between'>
                        <span
                          className={cn(
                            'inline-flex size-6 items-center justify-center rounded-full text-xs tabular-nums',
                            day === today && 'bg-primary font-semibold text-primary-foreground',
                          )}>
                          {Number(day.slice(8))}
                        </span>
                        <Plus className='size-3.5 text-faint opacity-0 group-hover:opacity-100' aria-hidden />
                      </div>
                      {dayItems.slice(0, MAX_IN_CELL).map(i => (
                        <ItemChip key={i.key} item={i} conflict={conflicts.has(i.key)} onOpen={() => onOpenItem(i)} />
                      ))}
                      {dayItems.length > MAX_IN_CELL && (
                        <button
                          type='button'
                          onPointerDown={e => e.stopPropagation()}
                          onClick={e => {
                            e.stopPropagation();
                            if (allowTime) {
                              setAnchor(day);
                              setView('week');
                            } else onOpenItem(dayItems[MAX_IN_CELL]);
                          }}
                          className='px-1.5 text-left text-2xs text-muted-foreground hover:underline'>
                          +{dayItems.length - MAX_IN_CELL}개 더
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        ) : (
          <div className='overflow-hidden rounded-lg border bg-card'>
            <div
              role='grid'
              aria-label={`${title} 종일 항목. 날짜를 누르거나 끌어서 종일 일정 추가`}
              className='grid grid-cols-[52px_repeat(7,minmax(0,1fr))] border-b'>
              <div className='border-r' />
              {week.map((day, i) => (
                <div
                  key={day}
                  {...dayCellProps(day)}
                  className={cn(
                    'flex min-h-14 cursor-pointer flex-col gap-0.5 border-r p-1 outline-none last:border-r-0 hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                    inRange(day, dayRange) && 'bg-accent/70',
                  )}>
                  <div className={cn('text-xs', i >= 5 ? 'text-destructive/70' : 'text-faint', day === today && 'font-semibold text-primary')}>
                    {WEEKDAYS[i]} {Number(day.slice(8))}
                  </div>
                  {allDayItems(day).map(it => (
                    <ItemChip key={it.key} item={it} compact onOpen={() => onOpenItem(it)} />
                  ))}
                </div>
              ))}
            </div>
            <div
              ref={weekScroll}
              className='max-h-[560px] overflow-y-auto'
              onPointerUp={finishTimeDrag}
              onPointerLeave={() => timeDrag && finishTimeDrag()}>
              <div className='relative grid grid-cols-[52px_repeat(7,minmax(0,1fr))]'>
                <div className='border-r'>
                  {Array.from({ length: 24 }, (_, h) => (
                    <div key={h} style={{ height: SLOT_PX * 2 }} className='-translate-y-1.5 pr-1.5 text-right text-2xs tabular-nums text-faint'>
                      {h === 0 ? '' : `${h}:00`}
                    </div>
                  ))}
                </div>
                {week.map(day => (
                  <div key={day} className='relative border-r last:border-r-0'>
                    {Array.from({ length: (24 * 60) / SLOT }, (_, s) => {
                      const minute = s * SLOT;
                      const selected =
                        timeDrag?.day === day && minute >= Math.min(timeDrag.from, timeDrag.to) && minute <= Math.max(timeDrag.from, timeDrag.to);
                      return (
                        <div
                          key={s}
                          role='button'
                          tabIndex={-1}
                          aria-label={`${dayLabel(day)} ${Math.floor(minute / 60)}시 ${minute % 60}분에 일정 추가`}
                          style={{ height: SLOT_PX }}
                          className={cn(
                            'cursor-pointer border-b border-border/50 hover:bg-muted/50',
                            s % 2 === 1 && 'border-border',
                            selected && 'bg-accent',
                          )}
                          onPointerDown={e => {
                            if (e.button !== 0) return;
                            // Touch input captures the pointer; release it so dragging reaches the next slots.
                            if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
                            setTimeDrag({ day, from: minute, to: minute });
                          }}
                          onPointerEnter={() => timeDrag?.day === day && setTimeDrag({ ...timeDrag, to: minute })}
                        />
                      );
                    })}
                    {layoutDay(sorted, day, tz).map(p => (
                      <div
                        key={p.item.key}
                        className='absolute px-0.5'
                        style={{
                          top: (p.top / SLOT) * SLOT_PX,
                          height: Math.max(SLOT_PX, ((p.bottom - p.top) / SLOT) * SLOT_PX) - 2,
                          left: `${(p.lane / p.lanes) * 100}%`,
                          width: `${100 / p.lanes}%`,
                        }}>
                        <button
                          type='button'
                          onPointerDown={e => e.stopPropagation()}
                          onClick={() => onOpenItem(p.item)}
                          className={cn(
                            'flex h-full w-full flex-col overflow-hidden rounded-sm px-1.5 py-0.5 text-left text-2xs hover:brightness-95',
                            TONE_CLASS[p.item.tone],
                            p.conflict && 'ring-1 ring-warning',
                          )}>
                          <span className='truncate font-medium'>{p.item.title}</span>
                          <span className='truncate tabular-nums opacity-80'>
                            {timeOnly(p.item.start)}
                            {p.item.end ? `–${timeOnly(p.item.end)}` : ''}
                          </span>
                        </button>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Narrow screens: the month as a day-by-day list. */}
      <ol className='flex flex-col md:hidden' aria-label={`${title} 일정 목록`}>
        {weeks
          .flat()
          .filter(day => day.slice(0, 7) === month)
          .map(day => {
            const dayItems = sorted.filter(i => coversDay(i, day, tz));
            return (
              <li key={day} className='flex gap-3 border-b py-2'>
                <div className={cn('w-14 shrink-0 pt-0.5 text-xs text-faint', day === today && 'font-semibold text-primary')}>
                  {dayLabel(day).replace(/^\d+월 /, '')}
                </div>
                <div className='flex min-w-0 flex-1 flex-col gap-1'>
                  {dayItems.map(i => (
                    <ItemChip key={i.key} item={i} conflict={conflicts.has(i.key)} onOpen={() => onOpenItem(i)} />
                  ))}
                  {!dayItems.length && <span className='text-xs text-faint'>{day === today ? '오늘은 비어 있습니다' : '일정 없음'}</span>}
                </div>
                <Button
                  size='icon-sm'
                  variant='ghost'
                  aria-label={`${dayLabel(day)}에 추가`}
                  onClick={() => onSelect({ kind: 'days', start: day, end: day })}>
                  <Plus />
                </Button>
              </li>
            );
          })}
      </ol>
    </div>
  );
}
