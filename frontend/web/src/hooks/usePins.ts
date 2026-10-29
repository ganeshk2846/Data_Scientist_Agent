import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { readHeadline } from '@/lib/headline';
import { loadPins, makePin, remeasure, reorder, savePins, type Pin } from '@/lib/pins';
import type { RunTransport } from '@/hooks/useRun';
import type { AnswerEnvelope } from '@/types/envelope';

/**
 * The pinboard's state, and the one live operation it has: Refresh.
 *
 * Refresh does not recompute anything. It re-asks the pin's own question
 * through the same transport the ask box uses, waits for the stream to go
 * terminal, collects the envelope, and replaces the stored figure with *that
 * envelope's* headline value. If the new run comes back without a headline
 * figure — a clarify, a refusal, an error — the pin keeps the figure it had and
 * the tile says when that figure was taken.
 */

export type RefreshState = 'idle' | 'running' | 'failed';

export interface PinsController {
  pins: readonly Pin[];
  /** Null when the envelope states no single headline figure. */
  add: (question: string, envelope: AnswerEnvelope) => Pin | null;
  remove: (pinId: string) => void;
  move: (from: number, to: number) => void;
  refresh: (pinId: string) => void;
  refreshAll: () => void;
  state: (pinId: string) => RefreshState;
  /** True for a tile whose value has just been replaced, so it can count in. */
  justMeasured: (pinId: string) => boolean;
  isPinned: (question: string) => boolean;
}

export function usePins(transport: RunTransport): PinsController {
  const [pins, setPins] = useState<readonly Pin[]>(loadPins);
  const [states, setStates] = useState<Readonly<Record<string, RefreshState>>>({});
  const [fresh, setFresh] = useState<readonly string[]>([]);
  /** Every stream opened by a refresh, so unmount can close all of them. */
  const open = useRef(new Map<string, () => void>());

  useEffect(() => savePins(pins), [pins]);

  useEffect(
    () => () => {
      for (const close of open.current.values()) close();
      open.current.clear();
    },
    [],
  );

  const setState = useCallback((pinId: string, state: RefreshState) => {
    setStates((current) => ({ ...current, [pinId]: state }));
  }, []);

  const add = useCallback((question: string, envelope: AnswerEnvelope) => {
    const headline = readHeadline(envelope);
    if (!headline) return null;
    const pin = makePin(question, headline, envelope.run_id);
    setPins((current) => [pin, ...current]);
    return pin;
  }, []);

  const remove = useCallback((pinId: string) => {
    open.current.get(pinId)?.();
    open.current.delete(pinId);
    setPins((current) => current.filter((pin) => pin.pinId !== pinId));
  }, []);

  const move = useCallback((from: number, to: number) => {
    setPins((current) => reorder(current, from, to));
  }, []);

  const refresh = useCallback(
    (pinId: string) => {
      setPins((current) => {
        const pin = current.find((candidate) => candidate.pinId === pinId);
        if (!pin) return current;
        if (open.current.has(pinId)) return current;

        setState(pinId, 'running');

        void (async () => {
          const close = () => {
            open.current.delete(pinId);
          };
          try {
            const runId = await transport.ask(pin.question, null);
            await new Promise<void>((resolve) => {
              const handle = transport.stream(runId, {
                onEvent: () => {},
                onComplete: () => {
                  handle.close();
                  resolve();
                },
                onTransportError: (willRetry) => {
                  if (!willRetry) {
                    handle.close();
                    resolve();
                  }
                },
              });
              open.current.set(pinId, () => {
                handle.close();
                resolve();
              });
            });
            const controller = new AbortController();
            const envelope = await transport.getRun(runId, controller.signal);
            const headline = readHeadline(envelope);
            if (!headline) {
              setState(pinId, 'failed');
              close();
              return;
            }
            setPins((latest) =>
              latest.map((candidate) =>
                candidate.pinId === pinId
                  ? remeasure(candidate, headline, envelope.run_id)
                  : candidate,
              ),
            );
            setState(pinId, 'idle');
            setFresh((current) => [...current, pinId]);
            // The tile animates its new value in; the mark clears afterwards.
            window.setTimeout(
              () => setFresh((current) => current.filter((id) => id !== pinId)),
              1_400,
            );
          } catch {
            setState(pinId, 'failed');
          } finally {
            close();
          }
        })();

        return current;
      });
    },
    [setState, transport],
  );

  const refreshAll = useCallback(() => {
    for (const pin of pins) refresh(pin.pinId);
  }, [pins, refresh]);

  const questions = useMemo(
    () => new Set(pins.map((pin) => pin.question.trim().toLowerCase())),
    [pins],
  );

  return {
    pins,
    add,
    remove,
    move,
    refresh,
    refreshAll,
    state: (pinId) => states[pinId] ?? 'idle',
    justMeasured: (pinId) => fresh.includes(pinId),
    isPinned: (question) => questions.has(question.trim().toLowerCase()),
  };
}
