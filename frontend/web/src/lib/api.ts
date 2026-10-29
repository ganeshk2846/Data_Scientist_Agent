/**
 * The HTTP surface. Three real endpoints, all proxied through the Vite dev
 * server at `/api`, so the backend needs no CORS change.
 */

import { getApiToken } from './storage';
import type { AnswerEnvelope, AskResponse, RunPending } from '@/types/envelope';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** A fetch that failed before getting a response at all. */
export class OfflineError extends Error {
  constructor(message = 'The agent service is not reachable.') {
    super(message);
    this.name = 'OfflineError';
  }
}

export function authHeaders(): Record<string, string> {
  const token = getApiToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function readDetail(response: Response): Promise<string | undefined> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === 'object' && 'detail' in body) {
      const { detail } = body as { detail: unknown };
      if (typeof detail === 'string') return detail;
      // FastAPI validation errors arrive as a list of objects.
      if (Array.isArray(detail)) return detail.map((item) => String(item)).join('; ');
    }
  } catch {
    // A non-JSON error body is not worth surfacing.
  }
  return undefined;
}

/** `POST /api/ask` → a run id. 422 means the guard or the contract rejected it. */
export async function ask(params: {
  question: string;
  sessionId: string;
  clarificationOf?: string | null;
  signal?: AbortSignal;
}): Promise<AskResponse> {
  let response: Response;
  try {
    response = await fetch('/api/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
      },
      body: JSON.stringify({
        question: params.question,
        session_id: params.sessionId,
        clarification_of: params.clarificationOf ?? null,
      }),
      ...(params.signal ? { signal: params.signal } : {}),
    });
  } catch {
    throw new OfflineError();
  }

  if (!response.ok) {
    throw new ApiError(
      `POST /api/ask failed with ${response.status}`,
      response.status,
      await readDetail(response),
    );
  }
  return (await response.json()) as AskResponse;
}

function isPending(body: unknown): body is RunPending {
  return (
    !!body &&
    typeof body === 'object' &&
    'status' in body &&
    (body as { status: unknown }).status === 'running'
  );
}

/**
 * `GET /api/runs/{id}` with backoff.
 *
 * The endpoint blocks server-side in `wait_for_envelope(timeout=15.0)` before
 * it answers 202, so a single request can legitimately hang for 15 s. We abort
 * our own request at 10 s and retry rather than hold the connection open, then
 * back off 400/800/1600/3200 ms (capped) until the overall deadline.
 */
export async function getRun(
  runId: string,
  options: { signal?: AbortSignal; deadlineMs?: number } = {},
): Promise<AnswerEnvelope> {
  const deadline = Date.now() + (options.deadlineMs ?? 60_000);
  let delay = 400;
  let lastStatus = 0;

  while (Date.now() < deadline) {
    if (options.signal?.aborted) throw new DOMException('Aborted', 'AbortError');

    // One timeout per attempt, folded together with the caller's signal.
    const attempt = new AbortController();
    const onAbort = () => attempt.abort();
    options.signal?.addEventListener('abort', onAbort, { once: true });
    const timer = window.setTimeout(() => attempt.abort(), 10_000);

    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`, {
        headers: authHeaders(),
        signal: attempt.signal,
      });
      lastStatus = response.status;

      if (response.status === 404) {
        throw new ApiError('That run is no longer in the service store.', 404);
      }
      if (response.ok) {
        const body: unknown = await response.json();
        if (!isPending(body)) return body as AnswerEnvelope;
      } else if (response.status !== 202) {
        throw new ApiError(
          `GET /api/runs/${runId} failed with ${response.status}`,
          response.status,
          await readDetail(response),
        );
      } else {
        // 202 bodies are RunPending, never an envelope.
        await response.json().catch(() => undefined);
      }
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (options.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      // Our own 10 s abort, or a network failure: both are worth one more try.
      if (!(error instanceof DOMException) && !(error instanceof TypeError)) throw error;
    } finally {
      window.clearTimeout(timer);
      options.signal?.removeEventListener('abort', onAbort);
    }

    await new Promise((resolve) => window.setTimeout(resolve, delay));
    delay = Math.min(delay * 2, 3_200);
  }

  throw new ApiError(
    'The run did not produce an answer in time.',
    lastStatus || 504,
  );
}

/**
 * There is no health endpoint, so probe a run id that cannot exist: a network
 * failure means the service is down, while a 404 means it answered us.
 */
export async function probeBackend(): Promise<boolean> {
  try {
    await fetch('/api/runs/__probe__', { method: 'GET', headers: authHeaders() });
    return true;
  } catch {
    return false;
  }
}
