/**
 * The SSE event contract, derived strictly from the `_emit` calls in
 * `backend/src/service.py`. Do not add event types or stage names the backend
 * never emits.
 *
 * Wire format (`service.py:format_sse_event`):
 *   id: <seq>
 *   event: <type>
 *   data: <the whole event object as JSON>
 *
 * Keep-alives arrive as bare SSE comment lines and never surface to
 * `EventSource` listeners.
 */

import type { RunStatus } from './envelope';

/** Every event carries these. `seq` is also the SSE `id`, for Last-Event-ID. */
interface RunEventBase {
  seq: number;
  run_id: string;
}

/** The seven step ids the backend actually emits. */
export type StepId = '1' | '2' | '7' | '9' | '11' | '12' | '14';

/** The exact `component` strings paired with each step id in service.py. */
export type StepComponent =
  | 'Guard'
  | 'Router and Extractor'
  | 'SQL Compiler'
  | 'Executor'
  | 'Analysts'
  | 'Evidence Ledger'
  | 'Fact Checker';

export type StepStatus = 'ok' | 'failed';

export interface StepStartedEvent extends RunEventBase {
  type: 'step_started';
  step: StepId;
  component: StepComponent;
  /** ISO-8601 UTC, millisecond precision. */
  at: string;
}

export interface StepFinishedEvent extends RunEventBase {
  type: 'step_finished';
  step: StepId;
  component: StepComponent;
  status: StepStatus;
  duration_ms: number;
  summary: string;
}

/**
 * Emitted when the envelope carries a clarification. NOT terminal: an `answer`
 * event with `status: 'clarify'` follows it.
 */
export interface ClarifyEvent extends RunEventBase {
  type: 'clarify';
  what_understood: string;
  what_needs_clarification: string;
}

/** Terminal. */
export interface AnswerEvent extends RunEventBase {
  type: 'answer';
  status: RunStatus;
}

/** Terminal. */
export interface ErrorEvent extends RunEventBase {
  type: 'error';
  error: {
    code: string;
    message: string;
    retriable: boolean;
  };
}

export type RunEvent =
  | StepStartedEvent
  | StepFinishedEvent
  | ClarifyEvent
  | AnswerEvent
  | ErrorEvent;

export type RunEventType = RunEvent['type'];

/** The only event types the backend emits, for `addEventListener` wiring. */
export const RUN_EVENT_TYPES: readonly RunEventType[] = [
  'step_started',
  'step_finished',
  'clarify',
  'answer',
  'error',
];

/** `RunStore.append` marks the run terminal on these, and the stream ends. */
export const TERMINAL_EVENT_TYPES: readonly RunEventType[] = ['answer', 'error'];

export function isTerminalEvent(event: RunEvent): event is AnswerEvent | ErrorEvent {
  return event.type === 'answer' || event.type === 'error';
}
