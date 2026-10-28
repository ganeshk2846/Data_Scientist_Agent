import { useCallback, useEffect, useReducer, useRef } from 'react';

import { ApiError, OfflineError, ask, getRun } from '@/lib/api';
import { openRunStream, type StreamHandle } from '@/lib/sse';
import { IDLE_RUN, runReducer, type RunState } from '@/lib/runState';
import type { AnswerEnvelope } from '@/types/envelope';

/**
 * The transport a run uses. The live implementation talks to the backend; the
 * mock implementation in `lib/mock/` satisfies the same shape, so `useRun` is
 * identical in both modes.
 */
export interface RunTransport {
  ask: (question: string, clarificationOf: string | null) => Promise<string>;
  stream: (
    runId: string,
    handlers: Parameters<typeof openRunStream>[1],
  ) => StreamHandle;
  getRun: (runId: string, signal: AbortSignal) => Promise<AnswerEnvelope>;
}

export function liveTransport(sessionId: string): RunTransport {
  return {
    ask: async (question, clarificationOf) => {
      const response = await ask({ question, sessionId, clarificationOf });
      return response.run_id;
    },
    stream: openRunStream,
    getRun: (runId, signal) => getRun(runId, { signal }),
  };
}

export interface RunController {
  state: RunState;
  submit: (question: string, clarificationOf?: string | null) => void;
  reset: () => void;
  restore: (envelope: AnswerEnvelope, question: string, localId: string) => void;
}

interface UseRunOptions {
  transport: RunTransport;
  /** Opens a history row and returns its local id. */
  openHistory: (question: string, clarificationOf: string | null) => string;
  onRunId: (localId: string, runId: string) => void;
  onEnvelope: (localId: string, envelope: AnswerEnvelope) => void;
}

export function useRun({
  transport,
  openHistory,
  onRunId,
  onEnvelope,
}: UseRunOptions): RunController {
  const [state, dispatch] = useReducer(runReducer, IDLE_RUN);
  const streamRef = useRef<StreamHandle | null>(null);
  const fetchRef = useRef<AbortController | null>(null);
  /** Guards against a late response from a run the user has moved on from. */
  const generation = useRef(0);

  const teardown = useCallback(() => {
    streamRef.current?.close();
    streamRef.current = null;
    fetchRef.current?.abort();
    fetchRef.current = null;
  }, []);

  useEffect(() => teardown, [teardown]);

  const collect = useCallback(
    async (runId: string, localId: string, mine: number) => {
      const controller = new AbortController();
      fetchRef.current = controller;
      dispatch({ kind: 'fetching' });
      try {
        const envelope = await transport.getRun(runId, controller.signal);
        if (generation.current !== mine) return;
        dispatch({ kind: 'settled', envelope });
        onEnvelope(localId, envelope);
      } catch (error) {
        if (generation.current !== mine) return;
        if (error instanceof DOMException && error.name === 'AbortError') return;
        dispatch({
          kind: 'failed',
          title: 'The answer could not be collected',
          detail:
            error instanceof ApiError || error instanceof Error
              ? error.message
              : 'An unknown error interrupted the request.',
          failureKind: error instanceof OfflineError ? 'offline' : 'request',
        });
      }
    },
    [onEnvelope, transport],
  );

  const submit = useCallback(
    (question: string, clarificationOf: string | null = null) => {
      const trimmed = question.trim();
      if (!trimmed) return;

      teardown();
      const mine = (generation.current += 1);
      const localId = openHistory(trimmed, clarificationOf);
      dispatch({ kind: 'submit', question: trimmed, localId });

      void (async () => {
        let runId: string;
        try {
          runId = await transport.ask(trimmed, clarificationOf);
        } catch (error) {
          if (generation.current !== mine) return;
          if (error instanceof OfflineError) {
            dispatch({
              kind: 'failed',
              title: 'The agent service is not reachable',
              detail:
                'Nothing answered at /api. Start the backend, or append ?mock=1 to preview the interface with sample answers.',
              failureKind: 'offline',
            });
            return;
          }
          dispatch({
            kind: 'failed',
            title: 'The question was not accepted',
            detail:
              error instanceof ApiError
                ? (error.detail ?? error.message)
                : 'An unknown error interrupted the request.',
            failureKind: 'request',
          });
          return;
        }

        if (generation.current !== mine) return;
        dispatch({ kind: 'accepted', runId });
        onRunId(localId, runId);

        streamRef.current = transport.stream(runId, {
          onEvent: (event) => {
            if (generation.current !== mine) return;
            dispatch({ kind: 'event', event });
          },
          onComplete: () => {
            if (generation.current !== mine) return;
            void collect(runId, localId, mine);
          },
          onTransportError: (willRetry) => {
            if (generation.current !== mine) return;
            dispatch({ kind: 'reconnecting', value: willRetry });
            // Out of retries: the run may still have finished, so ask directly.
            if (!willRetry) void collect(runId, localId, mine);
          },
        });
      })();
    },
    [collect, openHistory, onRunId, teardown, transport],
  );

  const reset = useCallback(() => {
    teardown();
    generation.current += 1;
    dispatch({ kind: 'reset' });
  }, [teardown]);

  const restore = useCallback(
    (envelope: AnswerEnvelope, question: string, localId: string) => {
      teardown();
      generation.current += 1;
      dispatch({ kind: 'restore', envelope, question, localId });
    },
    [teardown],
  );

  return { state, submit, reset, restore };
}
