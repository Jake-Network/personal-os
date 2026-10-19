'use client';

import { useEffect, useState } from 'react';

import { CalendarDays, List } from 'lucide-react';

import { cn } from '@/lib/utils';

export type ViewMode = 'list' | 'calendar';

/** List or calendar for one record type; the choice is remembered per screen. */
export function ViewToggle({ value, onChange }: { value: ViewMode; onChange: (v: ViewMode) => void }) {
  const item = (mode: ViewMode, label: string, Icon: typeof List) => (
    <button
      type='button'
      aria-pressed={value === mode}
      onClick={() => onChange(mode)}
      className={cn('inline-flex h-7 items-center gap-1 rounded-sm px-2.5 text-ui text-muted-foreground', value === mode && 'bg-card font-medium text-foreground shadow-sm')}>
      <Icon className='size-3.5' aria-hidden />
      {label}
    </button>
  );
  return (
    <div className='inline-flex rounded-md bg-muted p-0.5' role='group' aria-label='보기 방식'>
      {item('list', '목록', List)}
      {item('calendar', '달력', CalendarDays)}
    </div>
  );
}

/** The last choice for a screen, kept only in this browser (a convenience, not data). */
export function useStoredView(key: string, fallback: ViewMode = 'list'): [ViewMode, (v: ViewMode) => void] {
  const [value, setValue] = useState<ViewMode>(fallback);
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(`view:${key}`);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- browser storage is only readable after hydration
      if (stored === 'list' || stored === 'calendar') setValue(stored);
    } catch {
      // Storage unavailable: keep the default.
    }
  }, [key]);
  const change = (v: ViewMode) => {
    setValue(v);
    try {
      window.localStorage.setItem(`view:${key}`, v);
    } catch {
      // The choice just isn't remembered.
    }
  };
  return [value, change];
}
