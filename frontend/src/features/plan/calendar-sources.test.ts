import { afterEach, describe, expect, it } from 'vitest';

import { setDisplayTimeZone } from '@/lib/utils/format';

import { SOURCES } from './calendar-sources';

describe('calendar sources', () => {
  afterEach(() => setDisplayTimeZone(undefined));

  it('turns a picked day range into an all-day event over local midnights', () => {
    setDisplayTimeZone('Asia/Seoul');
    expect(SOURCES['calendar-events'].defaults({ kind: 'days', start: '2026-10-17', end: '2026-10-18' }).values).toEqual({
      all_day: true,
      starts_at: '2026-10-16T15:00:00.000Z',
      ends_at: '2026-10-18T15:00:00.000Z',
    });
    expect(SOURCES['calendar-events'].defaults({ kind: 'time', day: '2026-10-18', startMinute: 570, endMinute: 630 }).values).toEqual({
      all_day: false,
      starts_at: '2026-10-18T00:30:00.000Z',
      ends_at: '2026-10-18T01:30:00.000Z',
    });
  });

  it('uses only the first day for single-date records and says so', () => {
    const picked = SOURCES.tasks.defaults({ kind: 'days', start: '2026-10-20', end: '2026-10-22' });
    expect(picked.values).toEqual({ due_on: '2026-10-20' });
    expect(picked.note).toContain('첫날');
    expect(SOURCES.tasks.defaults({ kind: 'days', start: '2026-10-20', end: '2026-10-20' }).note).toBeUndefined();
  });

  it('marks overdue open tasks but not finished ones', () => {
    const items = SOURCES.tasks.toItems(
      [
        { id: 1, title: 'a', status: 'todo', due_on: '2026-10-01' },
        { id: 2, title: 'b', status: 'done', due_on: '2026-10-01' },
        { id: 3, title: 'c', status: 'todo', due_on: null },
      ],
      { today: '2026-10-19' },
    );
    expect(items.map(i => [i.key, i.overdue, i.done])).toEqual([
      ['tasks:1', true, false],
      ['tasks:2', false, true],
    ]);
  });

  it('names interviews by their application', () => {
    const apps = new Map([[7, { id: 7, company: '합성회사', role: '백엔드' }]]);
    const [item] = SOURCES.interviews.toItems([{ id: 2, application_id: 7, stage: '1차', starts_at: '2026-10-20T01:00:00Z' }], { today: '2026-10-19', applications: apps });
    expect(item.title).toBe('합성회사 1차');
  });
});
