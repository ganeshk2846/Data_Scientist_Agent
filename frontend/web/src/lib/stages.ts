/**
 * The pipeline stage registry.
 *
 * Every entry here corresponds to a real `_emit('step_started' | ...)` call in
 * `backend/src/service.py`. Nothing is invented. The step ids are sparse
 * (1, 2, 7, 9, 11, 12, 14) because they are positions in the full design DAG,
 * not a dense sequence.
 *
 * Conditional stages are only emitted on some paths:
 *   - steps 7 and 9  : primary route is one of lookup / anomaly / driver
 *   - step 11        : the orchestrator produced analyst outputs
 */

import type { StepComponent, StepId } from '@/types/events';

export interface StageDefinition {
  step: StepId;
  /** The exact `component` string on the wire. */
  component: StepComponent;
  /** The short editorial label shown on the track. */
  label: string;
  /** One line explaining the stage, for the hover detail. */
  blurb: string;
  /** False when the backend only emits this stage on some routes. */
  always: boolean;
}

export const STAGES: readonly StageDefinition[] = [
  {
    step: '1',
    component: 'Guard',
    label: 'Guard',
    blurb: 'Ingress safety: write attempts and prompt injection are blocked here.',
    always: true,
  },
  {
    step: '2',
    component: 'Router and Extractor',
    label: 'Router',
    blurb: 'Three-signal intent routing and slot extraction.',
    always: true,
  },
  {
    step: '7',
    component: 'SQL Compiler',
    label: 'SQL',
    blurb: 'Governed metric compilation, or generation with bounded repair.',
    always: false,
  },
  {
    step: '9',
    component: 'Executor',
    label: 'Executor',
    blurb: 'Read-only execution through the gateway.',
    always: false,
  },
  {
    step: '11',
    component: 'Analysts',
    label: 'Analysts',
    blurb: 'Typed anomaly and driver attribution modules.',
    always: false,
  },
  {
    step: '12',
    component: 'Evidence Ledger',
    label: 'Ledger',
    blurb: 'Every row and analyst output becomes a numbered claim.',
    always: true,
  },
  {
    step: '14',
    component: 'Fact Checker',
    label: 'Fact check',
    blurb: 'Sentences carrying unapproved numbers are removed.',
    always: true,
  },
];

export const STAGES_BY_STEP: ReadonlyMap<StepId, StageDefinition> = new Map(
  STAGES.map((stage) => [stage.step, stage]),
);

export type StageState = 'pending' | 'running' | 'ok' | 'failed' | 'skipped';

export interface StageProgress {
  definition: StageDefinition;
  state: StageState;
  /** From `step_finished.duration_ms`; null until the stage finishes. */
  durationMs: number | null;
  /** From `step_finished.summary`. */
  summary: string | null;
  /** From `step_started.at`. */
  startedAt: string | null;
}

export function initialStageProgress(): StageProgress[] {
  return STAGES.map((definition) => ({
    definition,
    state: 'pending' as StageState,
    durationMs: null,
    summary: null,
    startedAt: null,
  }));
}
