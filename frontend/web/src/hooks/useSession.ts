import { useCallback, useEffect, useMemo, useState } from 'react';

import { loadHistory, saveHistory, type StoredEntry } from '@/lib/historyStore';
import { KEYS, removeRaw } from '@/lib/storage';
import type { AnswerEnvelope, RunStatus } from '@/types/envelope';

/**
 * This browser's question history.
 *
 * It persists to localStorage: the envelope is a complete, self-contained
 * document, so a briefing can be reopened from our own copy long after the
 * backend's process-local run store has forgotten the run. Every surface that
 * reads it labels it as stored locally — see `lib/historyStore.ts`.
 */

export type HistoryEntry = StoredEntry;

export interface SessionController {
  sessionId: string;
  history: readonly HistoryEntry[];
  /** Appends a question and returns its local id. */
  open: (question: string, clarificationOf?: string | null, threadId?: string) => string;
  attachRunId: (localId: string, runId: string) => void;
  settle: (localId: string, envelope: AnswerEnvelope) => void;
  fail: (localId: string, status: RunStatus) => void;
  toggleStar: (localId: string) => void;
  /** Forgets everything stored in this browser. */
  clear: () => void;
  find: (localId: string) => HistoryEntry | undefined;
}

let counter = 0;
const nextLocalId = () => `q-${Date.now().toString(36)}-${(counter += 1)}`;

export function useSession(): SessionController {
  const sessionId = useMemo(
    () => `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    [],
  );
  const [history, setHistory] = useState<readonly HistoryEntry[]>(loadHistory);

  // One write per change, not one per keystroke: history only changes on a
  // submit, a settle or a star, all of which are rare.
  useEffect(() => saveHistory(history), [history]);

  const open = useCallback((question: string, clarificationOf: string | null = null, threadId?: string) => {
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
        starred: false,
        ...(threadId ? { threadId } : {}),
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

  const toggleStar = useCallback((localId: string) => {
    setHistory((current) =>
      current.map((entry) =>
        entry.localId === localId ? { ...entry, starred: !entry.starred } : entry,
      ),
    );
  }, []);

  const clear = useCallback(() => {
    setHistory([]);
    removeRaw(KEYS.history);
  }, []);

  const find = useCallback(
    (localId: string) => history.find((entry) => entry.localId === localId),
    [history],
  );

  return {
    sessionId,
    history,
    open,
    attachRunId,
    settle,
    fail,
    toggleStar,
    clear,
    find,
  };
}
