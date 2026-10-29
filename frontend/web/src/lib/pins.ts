/**
 * The pinboard.
 *
 * A pin is a question plus the headline figure the envelope stated when it was
 * pinned. It stores the figure, not a formula: refreshing a pin re-asks the
 * same question and replaces the stored figure with the new envelope's own
 * value. The frontend never recomputes a pinned number, and a pin whose run
 * came back without a headline figure keeps its last good value and says when
 * that was.
 */

import { KEYS, isRecord, readJson, writeJson } from './storage';
import type { Headline } from './headline';

export interface Pin {
  /** Stable id, so reordering and refreshing never depend on the question. */
  pinId: string;
  question: string;
  /** The figure, exactly as the envelope stated it. */
  value: number;
  unit: string;
  metric: string | null;
  period: string | null;
  source: Headline['source'];
  /** When this question was first pinned. */
  pinnedAt: number;
  /** When the stored figure was last taken from a live envelope. */
  measuredAt: number;
  /** The run the stored figure came from. */
  runId: string | null;
}

let counter = 0;
const nextPinId = () => `pin-${Date.now().toString(36)}-${(counter += 1)}`;

export function makePin(
  question: string,
  headline: Headline,
  runId: string | null,
): Pin {
  const now = Date.now();
  return {
    pinId: nextPinId(),
    question,
    value: headline.value,
    unit: headline.unit,
    metric: headline.metric,
    period: headline.period,
    source: headline.source,
    pinnedAt: now,
    measuredAt: now,
    runId,
  };
}

/** Replaces a pin's figure with a fresh envelope's own value. */
export function remeasure(pin: Pin, headline: Headline, runId: string | null): Pin {
  return {
    ...pin,
    value: headline.value,
    unit: headline.unit,
    metric: headline.metric,
    period: headline.period,
    source: headline.source,
    measuredAt: Date.now(),
    runId,
  };
}

function validatePin(value: unknown): Pin | null {
  if (!isRecord(value)) return null;
  const { pinId, question, value: figure, unit } = value;
  if (typeof pinId !== 'string' || typeof question !== 'string') return null;
  if (typeof figure !== 'number' || !Number.isFinite(figure)) return null;
  if (typeof unit !== 'string') return null;
  const source = value['source'];
  return {
    pinId,
    question,
    value: figure,
    unit,
    metric: typeof value['metric'] === 'string' ? value['metric'] : null,
    period: typeof value['period'] === 'string' ? value['period'] : null,
    source: source === 'anomaly' ? 'anomaly' : 'lookup',
    pinnedAt: typeof value['pinnedAt'] === 'number' ? value['pinnedAt'] : Date.now(),
    measuredAt:
      typeof value['measuredAt'] === 'number' ? value['measuredAt'] : Date.now(),
    runId: typeof value['runId'] === 'string' ? value['runId'] : null,
  };
}

const MAX_PINS = 24;

export function loadPins(): readonly Pin[] {
  const stored = readJson<readonly Pin[]>(KEYS.pins, (value) => {
    if (!Array.isArray(value)) return null;
    const pins: Pin[] = [];
    for (const entry of value) {
      const pin = validatePin(entry);
      if (pin) pins.push(pin);
    }
    return pins;
  });
  return stored ?? [];
}

export function savePins(pins: readonly Pin[]): void {
  writeJson(KEYS.pins, pins.slice(0, MAX_PINS));
}

/** Moves the pin at `from` so it sits at `to`, keeping every other order. */
export function reorder<T>(items: readonly T[], from: number, to: number): T[] {
  const next = [...items];
  if (from < 0 || from >= next.length || to < 0 || to >= next.length) return next;
  const [moved] = next.splice(from, 1);
  if (moved === undefined) return next;
  next.splice(to, 0, moved);
  return next;
}
