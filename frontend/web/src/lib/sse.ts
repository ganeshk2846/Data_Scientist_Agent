/**
 * The SSE transport for `GET /api/runs/{id}/events`.
 *
 * The backend names every event (`event: step_started`, …) and uses `seq` as
 * the SSE `id`, so named listeners are mandatory — a bare `onmessage` receives
 * nothing.
 *
 * Reconnect comes in two flavours, because `EventSource` cannot set headers:
 *   1. The browser's own retry on a dropped connection sends `Last-Event-ID`
 *      automatically, which is the mechanism the backend reads.
 *   2. Our manual retry, after we have torn a connection down, uses a fetch
 *      reader so we can set `Last-Event-ID` explicitly.
 *
 * Either way the consumer sees one ordered, de-duplicated stream: events whose
 * `seq` we have already delivered are dropped, so a replay from zero is safe.
 */

import { RUN_EVENT_TYPES, type RunEvent } from '@/types/events';

export interface StreamHandlers {
  onEvent: (event: RunEvent) => void;
  /** The stream ended because a terminal event arrived. */
  onComplete: () => void;
  /** Transport trouble. `willRetry` is false once we have given up. */
  onTransportError: (willRetry: boolean) => void;
}

export interface StreamHandle {
  close: () => void;
}

const MAX_RETRIES = 4;

function parseEvent(raw: string): RunEvent | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const candidate = parsed as { type?: unknown; seq?: unknown };
    if (typeof candidate.type !== 'string' || typeof candidate.seq !== 'number') return null;
    if (!RUN_EVENT_TYPES.includes(candidate.type as RunEvent['type'])) return null;
    return parsed as RunEvent;
  } catch {
    return null;
  }
}

export function openRunStream(runId: string, handlers: StreamHandlers): StreamHandle {
  const url = `/api/runs/${encodeURIComponent(runId)}/events`;
  let lastSeq = 0;
  let retries = 0;
  let closed = false;
  let source: EventSource | null = null;
  let abort: AbortController | null = null;
  let retryTimer = 0;

  const deliver = (event: RunEvent): boolean => {
    if (closed) return false;
    // Idempotent on seq: a replay from zero cannot double-apply.
    if (event.seq <= lastSeq) return false;
    lastSeq = event.seq;
    retries = 0;
    handlers.onEvent(event);
    if (event.type === 'answer' || event.type === 'error') {
      teardown();
      closed = true;
      handlers.onComplete();
      return true;
    }
    return false;
  };

  function teardown(): void {
    if (source) {
      source.close();
      source = null;
    }
    if (abort) {
      abort.abort();
      abort = null;
    }
    window.clearTimeout(retryTimer);
  }

  function scheduleRetry(): void {
    if (closed) return;
    if (retries >= MAX_RETRIES) {
      handlers.onTransportError(false);
      return;
    }
    retries += 1;
    handlers.onTransportError(true);
    const delay = Math.min(500 * 2 ** (retries - 1), 4_000);
    retryTimer = window.setTimeout(() => {
      if (!closed) resumeWithFetch();
    }, delay);
  }

  /** First attempt: EventSource, as the contract documents. */
  function connectEventSource(): void {
    source = new EventSource(url);
    for (const type of RUN_EVENT_TYPES) {
      source.addEventListener(type, (message) => {
        const event = parseEvent((message as MessageEvent<string>).data);
        if (event) deliver(event);
      });
    }
    source.onerror = () => {
      if (closed) return;
      // readyState CONNECTING means the browser is retrying on its own and
      // will send Last-Event-ID for us; leave it alone.
      if (source && source.readyState === EventSource.CONNECTING) return;
      teardown();
      scheduleRetry();
    };
  }

  /** Manual resume: a fetch reader, so `Last-Event-ID` can be set for real. */
  async function resumeWithFetch(): Promise<void> {
    abort = new AbortController();
    try {
      const response = await fetch(url, {
        headers: {
          Accept: 'text/event-stream',
          ...(lastSeq > 0 ? { 'Last-Event-ID': String(lastSeq) } : {}),
        },
        signal: abort.signal,
      });
      if (!response.ok || !response.body) {
        scheduleRetry();
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line.
        let boundary = buffer.indexOf('\n\n');
        while (boundary !== -1) {
          const frame = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          for (const line of frame.split('\n')) {
            if (!line.startsWith('data:')) continue;
            const event = parseEvent(line.slice(5).trim());
            if (event && deliver(event)) return;
          }
          boundary = buffer.indexOf('\n\n');
        }
      }
      if (!closed) scheduleRetry();
    } catch {
      if (!closed) scheduleRetry();
    }
  }

  connectEventSource();

  return {
    close: () => {
      closed = true;
      teardown();
    },
  };
}
