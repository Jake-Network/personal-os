import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearPrivateSession, getCsrfToken, registerPrivateStream, setCsrfToken } from './session';
import { postEventStream } from '@/api-client/event-stream';

afterEach(() => {
  clearPrivateSession();
  vi.unstubAllGlobals();
});

describe('private session boundary', () => {
  it('clears the CSRF proof and aborts every active stream on lock', () => {
    const first = new AbortController();
    const second = new AbortController();
    registerPrivateStream(first);
    registerPrivateStream(second);
    setCsrfToken('synthetic-csrf');
    clearPrivateSession();
    expect(getCsrfToken()).toBeNull();
    expect(first.signal.aborted).toBe(true);
    expect(second.signal.aborted).toBe(true);
  });

  it('attaches CSRF to streaming requests and propagates a lock to their fetch signal', async () => {
    setCsrfToken('synthetic-csrf');
    const fetchMock = vi.fn(
      (_path: string, options: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          options.signal?.addEventListener('abort', () => reject(new DOMException('Locked', 'AbortError')));
        }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const request = postEventStream('/api/advisor/ask', {}, () => undefined);
    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({ 'X-CSRF-Token': 'synthetic-csrf' });
    clearPrivateSession();
    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('does not deliver buffered events after the stream is locked', async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"text":"first"}\n\ndata: {"text":"late"}\n\n'));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body)));
    const received: string[] = [];
    await postEventStream<{ text: string }>('/api/advisor/ask', {}, event => {
      received.push(event.text);
      clearPrivateSession();
    });
    expect(received).toEqual(['first']);
  });
});
