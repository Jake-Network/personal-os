'use client';

import { useCallback, useState } from 'react';

export { parseRecordParam, recordHref } from '../utils/record-param';

/** `?record=<id>` deep links open a record's sheet; links from home, timeline, calendar and citations use it. */
export function useRecordParam(initial: number | null): [number | null, (id: number | null) => void] {
  const [id, setIdState] = useState(initial);
  const [seen, setSeen] = useState(initial);
  if (initial !== seen) {
    // A new navigation to the same page with another record.
    setSeen(initial);
    setIdState(initial);
  }
  const setId = useCallback((next: number | null) => {
    setIdState(next);
    const url = new URL(window.location.href);
    if (next === null) url.searchParams.delete('record');
    else url.searchParams.set('record', String(next));
    window.history.replaceState(window.history.state, '', url);
  }, []);
  return [id, setId];
}
