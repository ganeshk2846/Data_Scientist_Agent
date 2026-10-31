/**
 * V2 mock scenarios: one per intent, the compound question, a follow-up and
 * the clarification flow (round 1 → round 2 → answered), for `?mock=1`.
 *
 * Unlike the hand-written V1 samples, these envelopes and their event streams
 * were **captured from the real V2 pipeline** (`backend/src/pipeline_v2.py`)
 * running on the backend's synthetic test fixture, so they are
 * contract-accurate by construction. Their figures are the fixture's, not the
 * Olist snapshot's. The JSON is loaded on demand, so a live session never
 * downloads it.
 */

import type { RunEvent } from '@/lib/sse';
import type { RunStatus } from '@/types/envelope';
import type { AnswerEnvelopeV2 } from '@/types/v2';

export interface V2ScenarioMeta {
  id: string;
  /** A short label for the mock bar. */
  label: string;
  question: string;
  status: RunStatus;
}

/** Kept in step with `v2Scenarios.json`; listed here so the bar needs no JSON. */
export const V2_SCENARIOS: readonly V2ScenarioMeta[] = [
  { id: 'why', label: 'why', question: 'Why did revenue drop in the top category in April 2018?', status: 'answered' },
  { id: 'impact', label: 'so what', question: 'How much did the April 2018 drop cost us?', status: 'answered' },
  { id: 'forecast', label: 'forecast', question: 'Forecast revenue for the next 3 months', status: 'answered' },
  { id: 'forecast-live', label: 'forecast · live model', question: 'Forecast revenue in SP for the next 3 months', status: 'answered' },
  { id: 'whatif', label: 'what if', question: 'What if we raise prices 5%?', status: 'answered' },
  { id: 'nowwhat', label: 'segments', question: 'Which customer segment should we target?', status: 'answered' },
  {
    id: 'nowwhat-actions',
    label: 'now what',
    question: 'Why did August 2018 revenue fall, what did it cost, and what should we do?',
    status: 'answered',
  },
  { id: 'discovery', label: 'discovery', question: 'What data do you have?', status: 'answered' },
  { id: 'discovery-metrics', label: 'metrics', question: 'What metrics do you have?', status: 'answered' },
  { id: 'spikes', label: 'spikes', question: 'What are the spikes across all months?', status: 'answered' },
  {
    id: 'compound',
    label: 'compound',
    question: 'How does revenue trend look today and what will it be in 3 months?',
    status: 'answered',
  },
  { id: 'followup-base', label: 'follow-up · first', question: 'revenue in SP in July 2018', status: 'answered' },
  { id: 'followup', label: 'follow-up · what about', question: 'What about RJ?', status: 'answered' },
  { id: 'clarify-v2', label: 'clarify · options', question: 'Summarize revenue', status: 'clarify' },
];

interface Captured {
  id: string;
  question: string;
  status: RunStatus;
  envelope: AnswerEnvelopeV2;
  events: RunEvent[];
}

let cache: Promise<Map<string, Captured>> | null = null;

export function loadV2Scenarios(): Promise<Map<string, Captured>> {
  cache ??= import('./v2Scenarios.json').then((module) => {
    const list = (module.default as unknown as Captured[]) ?? [];
    return new Map(list.map((item) => [item.id, item]));
  });
  return cache;
}

/** The same capture, re-stamped with this mock run's id. */
export async function v2Run(id: string, runId: string): Promise<{ envelope: AnswerEnvelopeV2; events: RunEvent[] } | null> {
  const captured = (await loadV2Scenarios()).get(id);
  if (!captured) return null;
  const stamp = <T,>(value: T): T =>
    JSON.parse(JSON.stringify(value).split(`mock-v2-${id}`).join(runId)) as T;
  return { envelope: stamp(captured.envelope), events: stamp(captured.events) };
}

/**
 * Which V2 capture a typed question lands on, or null to fall through to the
 * V1 samples (so every V1 mock question still routes exactly as before).
 */
export function pickV2Scenario(question: string): string | null {
  const text = question.trim().toLowerCase();
  const exact = V2_SCENARIOS.find((item) => item.question.toLowerCase() === text);
  if (exact) return exact.id;
  if (/churn|risk|drop table|delete|truncate|roraima|by state/.test(text)) return null;
  if (/^what about\b/.test(text)) return 'followup';
  if (/^summari[sz]e\b/.test(text)) return 'clarify-v2';
  if (/what metrics|which metrics/.test(text)) return 'discovery-metrics';
  if (/what (data|tables)|which tables/.test(text)) return 'discovery';
  if (/what should we do|now what/.test(text)) return 'nowwhat-actions';
  if (/segment|should we target/.test(text)) return 'nowwhat';
  if (/what if|raise prices|lower prices|price (rise|cut|increase)/.test(text)) return 'whatif';
  if (/trend .* and what will/.test(text)) return 'compound';
  if (/forecast|next \d+ months|project(ed|ion)/.test(text)) {
    return /\bin (sp|rj|mg|rs|pr|ba)\b/.test(text) ? 'forecast-live' : 'forecast';
  }
  if (/cost us|what did .* cost|how much did/.test(text)) return 'impact';
  if (/spikes across|across all months/.test(text)) return 'spikes';
  if (/top category/.test(text)) return 'why';
  return null;
}

/** A reply to a V2 clarification: an option resolves; free text asks round 2, then resolves. */
export function clarifyFollowOn(previousId: string, optionId: string | null): string {
  if (optionId) return 'clarify-v2-resolved';
  return previousId === 'clarify-v2' ? 'clarify-v2-round2' : 'clarify-v2-resolved';
}

/** Mock pacing: real step durations, clamped so the live states are visible but brief. */
export function paceFor(event: RunEvent): number {
  switch (event.type) {
    case 'engine_running':
      return 1400; // long enough to read "Running model — this can take ~N s"
    case 'plan_step_finished':
      return Math.min(Math.max(event.duration_ms, 160), 700);
    case 'step_finished':
      return 140;
    default:
      return 110;
  }
}
