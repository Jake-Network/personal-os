import { describe, expect, it } from 'vitest';

import { parseEventBlocks } from './event-stream';

describe('parseEventBlocks', () => {
  it('returns complete data payloads and keeps the unfinished tail', () => {
    const { events, rest } = parseEventBlocks('data: {"type":"delta","text":"a"}\n\ndata: {"type":"de');
    expect(events).toEqual(['{"type":"delta","text":"a"}']);
    expect(rest).toBe('data: {"type":"de');
  });

  it('joins multi-line data and ignores comments and other fields', () => {
    const { events } = parseEventBlocks(': keepalive\n\nevent: msg\ndata: {"a":\ndata: 1}\n\n');
    expect(events).toEqual(['{"a":\n1}']);
  });
});
