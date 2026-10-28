import { useCallback, useMemo, useState } from 'react';

import type { AnswerEnvelope, RunStatus } from '@/types/envelope';

/**
 * This session's question history. Deliberately in-memory: the backend keeps
 * runs in a process-local store, so a reload cannot reopen them anyway.
 */

export interface HistoryEntry {
  /** Stable key, assigned before the run id exists. */
  localId: string;
  runId: string | null;
  question: string;
  askedAt: number;
  /** Null while the run is still in flight. */
  status: RunStatus | null;
  envelope: AnswerEnvelope | null;
  /** Set when this question was a clarification of an earlier run. */
  clarificationOf: string | null;
}

export interface SessionController {
  sessionId: string;
  history: readonly HistoryEntry[];
  /** Appends a question and returns its local id. */
  open: (question: string, clarificationOf?: string | null) => string;
  attachRunId: (localId: string, runId: string) => void;
  settle: (localId: string, envelope: AnswerEnvelope) => void;
  fail: (localId: string, status: RunStatus) => void;
  find: (localId: string) => HistoryEntry | undefined;
}

let counter = 0;
const nextLocalId = () => `q-${Date.now().toString(36)}-${(counter += 1)}`;

export function useSession(): SessionController {
  const sessionId = useMemo(
    () => `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    [],
  );
  const [history, setHistory] = useState<readonly HistoryEntry[]>([]);

  const open = useCallback((question: string, clarificationOf: string | null = null) => {
    const localId = nextLocalId();
    setHistory((current) => [
      {
        localId,
        runId: null,
        question,
        askedAt: Date.now(),
        status: null,
        envelope: null,
        clarificationOf,
      },
      ...current,
    ]);
    return localId;
  }, []);

  const patch = useCallback((localId: string, changes: Partial<HistoryEntry>) => {
    setHistory((current) =>
      current.map((entry) => (entry.localId === localId ? { ...entry, ...changes } : entry)),
    );
  }, []);

  const attachRunId = useCallback(
    (localId: string, runId: string) => patch(localId, { runId }),
    [patch],
  );

  const settle = useCallback(
    (localId: string, envelope: AnswerEnvelope) =>
      patch(localId, { envelope, status: envelope.status, runId: envelope.run_id }),
    [patch],
  );

  const fail = useCallback(
    (localId: string, status: RunStatus) => patch(localId, { status }),
    [patch],
  );

  const find = useCallback(
    (localId: string) => history.find((entry) => entry.localId === localId),
    [history],
  );

  return { sessionId, history, open, attachRunId, settle, fail, find };
}
