import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { CheckInStatus } from './check-in-status';
const render = (overrides: Partial<Parameters<typeof CheckInStatus>[0]>) =>
  renderToStaticMarkup(createElement(CheckInStatus, { todayConfirmed: true, month: '2026-09', pending: false, failed: false, ...overrides }));
it('reports existing and newly saved month evidence independently of today confirmation', () => {
  expect(render({ snapshot: { complete: true }, todayConfirmed: false })).toContain('오늘 확인 미완료');
  expect(render({ snapshot: { complete: true } })).toContain('월말 기록 완료');
  expect(render({ snapshot: { complete: false } })).toContain('월말 기록 근거 부족');
  expect(render({})).toContain('월말 기록 미완료');
});
it('does not call unavailable month evidence incomplete or completed', () => {
  expect(render({ pending: true })).toContain('월말 기록 확인 중');
  expect(render({ failed: true })).toContain('월말 기록 확인 실패');
});
