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
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw errorFromBody(res.status, await res.json().catch(() => null));
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const { events, rest } = parseEventBlocks(buffer + value);
    buffer = rest;
    events.forEach(data => onEvent(JSON.parse(data) as E));
  }
}
