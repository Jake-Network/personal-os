'use client';

import { useEffect, useState } from 'react';

import { CalendarDays, List } from 'lucide-react';

import { SegmentedControl } from '@/components/toggle-group';

export type ViewMode = 'list' | 'calendar';

/** List or calendar for one record type; the choice is remembered per screen. */
export function ViewToggle({ value, onChange }: { value: ViewMode; onChange: (v: ViewMode) => void }) {
  return (
    <SegmentedControl
      label='보기 방식'
      value={value}
      onChange={onChange}
      options={[
        { value: 'list', label: '목록', icon: List },
        { value: 'calendar', label: '달력', icon: CalendarDays },
      ]}
    />
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
