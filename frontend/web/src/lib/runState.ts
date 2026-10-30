/**
 * The run state machine. Pure, so it can be reasoned about and reused by the
 * mock transport without touching React.
 */

import { initialStageProgress, type StageProgress } from './stages';
import type { AnswerEnvelope } from '@/types/envelope';
import type { RunEvent } from './sse';
import type { ClarifyEvent, ErrorEvent } from '@/types/events';
import type { ClarifyEventV2Fields, ContextEvent, PlanEvent, ToolName, ToolStatus } from '@/types/v2';

/** One step of the V2 plan as it runs, from the plan_step_* events. */
export interface PlanStepProgress {
  stepId: string;
  tool: ToolName;
  purpose: string;
  dependsOn: readonly string[];
  state: 'pending' | 'running' | ToolStatus;
  /** True between `engine_running` and the step's finish: a live model fit. */
  modelRunning: boolean;
  durationMs: number | null;
  summary: string | null;
}

export type RunPhase =
  | 'idle'
  | 'submitting'
  | 'streaming'
  /** Terminal event seen; collecting the envelope from GET /api/runs/{id}. */
  | 'fetching'
  | 'settled'
  | 'failed';

export interface RunState {
  phase: RunPhase;
  question: string | null;
  runId: string | null;
  /** The history row this run belongs to. */
  localId: string | null;
  stages: readonly StageProgress[];
  /** Arrives before the terminal `answer` event, so it can be shown early. */
  clarify: (ClarifyEvent & ClarifyEventV2Fields) | null;
  /** V2: the decomposed plan, live. Empty for a V1 run. */
  plan: readonly PlanStepProgress[];
  /** V2: how a follow-up was read against the session's earlier turns. */
  context: ContextEvent | null;
  /** From a terminal `error` event. */
  streamError: ErrorEvent['error'] | null;
  envelope: AnswerEnvelope | null;
  /** A client-side failure: offline, submission rejected, fetch gave up. */
  failure: { title: string; detail: string; kind: 'offline' | 'request' } | null;
  /** True while the SSE transport is between attempts. */
  reconnecting: boolean;
  /** Wall clock at submission, so the elapsed timer measures the run. */
  startedAt: number | null;
}

export const IDLE_RUN: RunState = {
  phase: 'idle',
  question: null,
  runId: null,
  localId: null,
  stages: initialStageProgress(),
  clarify: null,
  plan: [],
  context: null,
  streamError: null,
  envelope: null,
  failure: null,
  reconnecting: false,
  startedAt: null,
};

export type RunAction =
  | { kind: 'submit'; question: string; localId: string }
  | { kind: 'accepted'; runId: string }
  | { kind: 'event'; event: RunEvent }
  | { kind: 'reconnecting'; value: boolean }
  | { kind: 'fetching' }
  | { kind: 'settled'; envelope: AnswerEnvelope }
  | { kind: 'failed'; title: string; detail: string; failureKind: 'offline' | 'request' }
  | { kind: 'reset' }
  /** Reopening a past answer from the rail. */
  | { kind: 'restore'; envelope: AnswerEnvelope; question: string; localId: string };

/**
 * Stages the run never reached are `skipped`, not left pending — steps 7, 9 and
 * 11 are conditional on the route, and an early failure can cut the rest short.
 */
function closeOutStages(stages: readonly StageProgress[]): StageProgress[] {
  return stages.map((stage) =>
    stage.state === 'pending' || stage.state === 'running'
      ? { ...stage, state: stage.state === 'running' ? 'failed' : 'skipped' }
      : stage,
  );
}

function planFrom(event: PlanEvent): PlanStepProgress[] {
  return event.steps.map((step) => ({
    stepId: step.step_id,
    tool: step.tool,
    purpose: step.purpose,
    dependsOn: step.depends_on,
    state: 'pending',
    modelRunning: false,
    durationMs: null,
    summary: null,
  }));
}

function patchStep(
  plan: readonly PlanStepProgress[],
  stepId: string,
  changes: Partial<PlanStepProgress>,
): PlanStepProgress[] {
  return plan.map((step) => (step.stepId === stepId ? { ...step, ...changes } : step));
}

function applyEvent(state: RunState, event: RunEvent): RunState {
  switch (event.type) {
    case 'context':
      return { ...state, context: event };
    case 'plan':
      // A re-plan replaces the checklist; the new plan is what runs.
      return { ...state, plan: planFrom(event) };
    case 'plan_step_started':
      return { ...state, plan: patchStep(state.plan, event.step_id, { state: 'running' }) };
    case 'engine_running':
      return { ...state, plan: patchStep(state.plan, event.step_id, { modelRunning: true }) };
    case 'plan_step_finished':
      return {
        ...state,
        plan: patchStep(state.plan, event.step_id, {
          state: event.status,
          modelRunning: false,
          durationMs: event.duration_ms,
          summary: event.summary,
        }),
      };
    case 'intent':
    case 'grounding':
    case 'compose':
    case 'replan':
      return state;

    case 'step_started':
      return {
        ...state,
        phase: 'streaming',
        reconnecting: false,
        stages: state.stages.map((stage) =>
          stage.definition.step === event.step
            ? { ...stage, state: 'running', startedAt: event.at }
            : stage,
        ),
      };

    case 'step_finished':
      return {
        ...state,
        reconnecting: false,
        stages: state.stages.map((stage) =>
          stage.definition.step === event.step
            ? {
                ...stage,
                state: event.status === 'ok' ? 'ok' : 'failed',
                durationMs: event.duration_ms,
                summary: event.summary,
              }
            : stage,
        ),
      };

    // Not terminal: an `answer` event with status "clarify" follows it.
    case 'clarify':
      return { ...state, clarify: event, reconnecting: false };

    case 'answer':
      return {
        ...state,
        phase: 'fetching',
        reconnecting: false,
        stages: closeOutStages(state.stages),
      };

    case 'error':
      return {
        ...state,
        phase: 'fetching',
        reconnecting: false,
        streamError: event.error,
        stages: closeOutStages(state.stages),
      };
  }
}

export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.kind) {
    case 'submit':
      return {
        ...IDLE_RUN,
        stages: initialStageProgress(),
        phase: 'submitting',
        question: action.question,
        localId: action.localId,
        startedAt: Date.now(),
      };
    case 'accepted':
      return { ...state, runId: action.runId, phase: 'streaming' };
    case 'event':
      return applyEvent(state, action.event);
    case 'reconnecting':
      return { ...state, reconnecting: action.value };
    case 'fetching':
      return { ...state, phase: 'fetching' };
    case 'settled':
      return { ...state, phase: 'settled', envelope: action.envelope };
    case 'failed':
      return {
        ...state,
        phase: 'failed',
        stages: closeOutStages(state.stages),
        failure: { title: action.title, detail: action.detail, kind: action.failureKind },
      };
    case 'restore':
      return {
        ...IDLE_RUN,
        phase: 'settled',
        question: action.question,
        localId: action.localId,
        runId: action.envelope.run_id,
        envelope: action.envelope,
        // A restored answer shows no live track; its stages are long finished.
        stages: [],
      };
    case 'reset':
      return { ...IDLE_RUN, stages: initialStageProgress() };
  }
}

/** True while the briefing should show skeletons rather than content. */
export function isRunInFlight(phase: RunPhase): boolean {
  return phase === 'submitting' || phase === 'streaming' || phase === 'fetching';
}
