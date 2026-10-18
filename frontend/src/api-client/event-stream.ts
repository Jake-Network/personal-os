import { getCsrfToken, notifySessionExpired, registerPrivateStream } from '@/features/security/session';

import { errorFromBody } from './api-error';

/** Splits buffered text/event-stream text into complete `data:` payloads and the unfinished tail. */
export function parseEventBlocks(buffer: string): { events: string[]; rest: string } {
  const events: string[] = [];
  let rest = buffer;
  let sep: number;
  while ((sep = rest.indexOf('\n\n')) !== -1) {
    const block = rest.slice(0, sep);
    rest = rest.slice(sep + 2);
    const data = block
      .split('\n')
      .filter(l => l.startsWith('data:'))
      .map(l => l.slice(5).trimStart())
      .join('\n');
    if (data) events.push(data);
  }
  return { events, rest };
}

/**
 * POST that answers with text/event-stream; calls onEvent for each `data:` JSON payload.
 * axios cannot stream response bodies in the browser, so this one call uses fetch.
 */
export async function postEventStream<E>(path: string, body: unknown, onEvent: (event: E) => void, signal?: AbortSignal): Promise<void> {
  return requestEventStream(path, { method: 'POST', body: JSON.stringify(body) }, onEvent, signal);
}

/** Observing a saved run never creates a new model request. Aborting only unsubscribes. */
export async function getEventStream<E>(path: string, onEvent: (event: E) => void, signal?: AbortSignal): Promise<void> {
  return requestEventStream(path, { method: 'GET' }, onEvent, signal);
}

async function requestEventStream<E>(
  path: string,
  request: Pick<RequestInit, 'method' | 'body'>,
  onEvent: (event: E) => void,
  signal?: AbortSignal,
): Promise<void> {
  const controller = new AbortController();
  const unregister = registerPrivateStream(controller);
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  try {
    const token = getCsrfToken();
    const res = await fetch(path, {
      ...request,
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...(token ? { 'X-CSRF-Token': token } : {}) },
      signal: controller.signal,
    });
    if (res.status === 401) notifySessionExpired();
    if (!res.ok || !res.body) throw errorFromBody(res.status, await res.json().catch(() => null));
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      const { events, rest } = parseEventBlocks(buffer + value);
      buffer = rest;
      if (controller.signal.aborted) break;
      for (const data of events) {
        if (controller.signal.aborted) break;
        onEvent(JSON.parse(data) as E);
      }
    }
  } finally {
    unregister();
    signal?.removeEventListener('abort', abort);
  }
}
