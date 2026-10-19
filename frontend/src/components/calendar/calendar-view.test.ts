import { createElement, type KeyboardEvent } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { setDisplayTimeZone } from '@/lib/utils/format';

import { CalendarView } from './calendar-view';

const { cells } = vi.hoisted(() => ({ cells: [] as Array<{ onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => void }> }));
// Retain the real server renderer and capture the handlers attached to its date cells.
vi.mock('react/jsx-runtime', async importOriginal => {
  const runtime = await importOriginal<typeof import('react/jsx-runtime')>();
  const capture =
    (factory: typeof runtime.jsx) =>
    (...args: Parameters<typeof runtime.jsx>) => {
      const props = args[1] as { role?: string; onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => void } | null;
      if (args[0] === 'div' && props?.role === 'gridcell') cells.push(props);
      return factory(...args);
    };
  return { ...runtime, jsx: capture(runtime.jsx), jsxs: capture(runtime.jsxs) };
});
vi.mock('react/jsx-dev-runtime', async importOriginal => {
  const runtime = await importOriginal<typeof import('react/jsx-dev-runtime')>();
  return {
    ...runtime,
    jsxDEV: (...args: Parameters<typeof runtime.jsxDEV>) => {
      const props = args[1] as { role?: string; onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => void } | null;
      if (args[0] === 'div' && props?.role === 'gridcell') cells.push(props);
      return runtime.jsxDEV(...args);
    },
  };
});

beforeEach(() => {
  cells.length = 0;
});
afterEach(() => {
  vi.useRealTimers();
  setDisplayTimeZone(undefined);
});

it('offers every empty day in the narrow-screen calendar for adding records', () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-19T03:00:00Z'));
  setDisplayTimeZone('Asia/Seoul');
  const html = renderToStaticMarkup(createElement(CalendarView, { items: [], onSelect: vi.fn(), onOpenItem: vi.fn() }));
  const mobile = html.slice(html.indexOf('<ol'));
  expect(mobile.match(/<li /g)).toHaveLength(31);
  expect(mobile).toContain('10월 31일');
});

it.each(['Enter', ' '])('preserves native %s activation on an existing event button', key => {
  const onSelect = vi.fn();
  renderToStaticMarkup(
    createElement(CalendarView, {
      items: [{ key: 'calendar-events:1', title: '면접', start: '2026-10-19', allDay: true, tone: 'event' }],
      onSelect,
      onOpenItem: vi.fn(),
    }),
  );
  expect(cells.length).toBeGreaterThan(0);
  const preventDefault = vi.fn();
  const currentTarget = {};
  cells[0].onKeyDown({ key, target: {}, currentTarget, preventDefault } as unknown as KeyboardEvent<HTMLDivElement>);
  expect(onSelect).not.toHaveBeenCalled();
  expect(preventDefault).not.toHaveBeenCalled();

  cells[0].onKeyDown({ key, target: currentTarget, currentTarget, preventDefault } as unknown as KeyboardEvent<HTMLDivElement>);
  expect(onSelect).toHaveBeenCalledOnce();
  expect(preventDefault).toHaveBeenCalledOnce();
});
