import { describe, expect, it } from 'vitest';

import type { RunCreate } from '@/api-client/model';

import { documentOptionsOf, initialDraft, planRunRequest, submitBlock } from './send-logic';

const base = {
  text: '퇴사해도 될까?',
  locked: false,
  sending: false,
  busy: false,
  waiting: false,
  providerNeedsSetup: false,
  forcedOnCount: 0,
  hasBaseline: false,
  webSearch: false,
  webQuery: '',
};

describe('advisor send logic', () => {
  it('blocks duplicate submits while a send is in flight or a run is executing', () => {
    expect(submitBlock(base)).toBeNull();
    expect(submitBlock({ ...base, locked: true })).toBe('locked');
    expect(submitBlock({ ...base, sending: true })).toBe('locked');
    expect(submitBlock({ ...base, busy: true })).toBe('busy');
    // A clarification answer is allowed while the run waits for it.
    expect(submitBlock({ ...base, busy: true, waiting: true })).toBeNull();
    expect(submitBlock({ ...base, text: '  ' })).toBe('empty');
  });

  it('waits for the adjusted sharing preview and a public query before a new question', () => {
    expect(submitBlock({ ...base, forcedOnCount: 1 })).toBe('share_pending');
    expect(submitBlock({ ...base, forcedOnCount: 1, hasBaseline: true })).toBeNull();
    expect(submitBlock({ ...base, webSearch: true })).toBe('web_query');
    expect(submitBlock({ ...base, webSearch: true, waiting: true, busy: true })).toBeNull();
  });

  it('starts every conversation view with a fresh draft', () => {
    expect(initialDraft(12, '3')).toMatchObject({ documentIds: null, webSearch: false, depth: 'auto', historyCompany: '' });
    expect(initialDraft(null, '3').documentIds).toEqual([3]);
    expect(initialDraft(null, 'x').documentIds).toBeNull();
    expect(documentOptionsOf({ ...initialDraft(null, null), webSearch: false, webQuery: '비공개' }).web_query).toBeNull();
  });

  it('requires explicit automatic recording opt-in and resets it for another conversation', () => {
    const fresh = initialDraft(12, null);
    expect(fresh.allowDataRecording).toBe(false);
    expect(documentOptionsOf(fresh).allow_data_recording).toBe(false);
    expect(documentOptionsOf({ ...fresh, allowDataRecording: true }).allow_data_recording).toBe(true);
    expect(initialDraft(13, null).allowDataRecording).toBe(false);
    const previous = { conversationId: 12, body: { message: '오늘 10km 뛰었어', request_id: 'old', allow_data_recording: false } as RunCreate };
    expect(planRunRequest(previous, { ...previous.body, request_id: 'new', allow_data_recording: true } as RunCreate, 12)).toEqual({ action: 'reconcile' });
  });

  it('reuses an uncertain request only when nothing the user controls changed', () => {
    const previous = { conversationId: 5, body: { message: 'q', request_id: 'old', exclude: [], depth: 'auto', parent_revision: 1 } as RunCreate };
    const same = { ...previous.body, request_id: 'new', parent_revision: 2 } as RunCreate;
    expect(planRunRequest(previous, same, 5)).toEqual({ action: 'send', body: previous.body });
    const changedSharing = { ...same, exclude: ['financial'] } as RunCreate;
    expect(planRunRequest(previous, changedSharing, 5)).toEqual({ action: 'reconcile' });
    const changedDepth = { ...same, depth: 'deep' } as RunCreate;
    expect(planRunRequest(previous, changedDepth, 5)).toEqual({ action: 'reconcile' });
    expect(planRunRequest(previous, changedSharing, 6)).toEqual({ action: 'send', body: changedSharing });
    expect(planRunRequest(null, same, 5)).toEqual({ action: 'send', body: same });
  });
});
