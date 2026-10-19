import { expect, it } from 'vitest';

import { updatePayload } from './use-resource';

it('completing a task keeps its other fields and drops server-managed ones', () => {
  const row = { id: 4, title: '이력서 정리', status: 'todo', priority: 'high', due_on: '2026-10-20', goal_id: 2, estimate_minutes: null, created_at: 'x', updated_at: 'y' };
  expect(updatePayload(row, { status: 'done' })).toEqual({
    title: '이력서 정리', status: 'done', priority: 'high', due_on: '2026-10-20', goal_id: 2, estimate_minutes: null,
  });
});
