import { describe, expect, it } from 'vitest';
import { applyRunEvent, type EventCursor } from './run-events';
import type { RunEvent } from '@/api-client/model';

const initial: EventCursor = { runId: 'run-a', seq: 0, answerRevision: 1, text: '' };
const event = (seq: number, payload = { text: '답변', answer_revision: 1 }, runId = 'run-a'): RunEvent => ({
  run_id: runId,
  seq,
  type: 'delta',
  revision: 1,
  payload,
  created_at: '2026-10-18T00:00:00Z',
});

describe('saved consultation events', () => {
  it('does not append a replayed event or a different conversation run', () => {
    const first = applyRunEvent(initial, event(1)).cursor;
    expect(applyRunEvent(first, event(1))).toEqual({ cursor: first, accepted: false, gap: false });
    expect(applyRunEvent(first, event(2, undefined, 'other-run')).cursor.text).toBe('답변');
  });
  it('keeps the cursor before a gap so reconnection requests the missing event', () => {
    expect(applyRunEvent(initial, event(2))).toEqual({ cursor: initial, accepted: false, gap: true });
  });
  it('replaces an interrupted answer when retry starts a new revision', () => {
    const previous = applyRunEvent(initial, event(1)).cursor;
    expect(applyRunEvent(previous, event(2, { text: '새 답변', answer_revision: 2 })).cursor.text).toBe('새 답변');
  });
});
