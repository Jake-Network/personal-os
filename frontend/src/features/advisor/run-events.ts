import type { RunEvent } from '@/api-client/model';

export interface EventCursor {
  runId: string;
  seq: number;
  answerRevision: number;
  text: string;
}

/** Reject stale/foreign events, replay gaps, and replace incomplete text on a new answer revision. */
export function applyRunEvent(cursor: EventCursor, event: RunEvent): { cursor: EventCursor; accepted: boolean; gap: boolean } {
  if (event.run_id !== cursor.runId || event.seq <= cursor.seq) return { cursor, accepted: false, gap: false };
  if (event.seq !== cursor.seq + 1) return { cursor, accepted: false, gap: true };
  const answerRevision = Number(event.payload.answer_revision ?? cursor.answerRevision);
  let text = answerRevision === cursor.answerRevision ? cursor.text : '';
  if (event.type === 'delta') text += String(event.payload.text ?? '');
  return { cursor: { ...cursor, seq: event.seq, answerRevision, text }, accepted: true, gap: false };
}
