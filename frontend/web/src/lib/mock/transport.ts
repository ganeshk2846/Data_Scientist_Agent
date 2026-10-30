/**
 * The mock transport: a simulated event stream and envelope fetch, satisfying
 * exactly the same `RunTransport` shape as the live one, so nothing downstream
 * knows the difference.
 *
 * The stream emits the same five event types, with the same fields and the same
 * sparse step ids, and respects the conditional stages — a clarify run never
 * emits steps 7, 9 or 11, because the real backend would not either.
 */

import { MOCK_SCENARIOS, pickScenario, type MockScenario } from './envelopes';
import { clarifyFollowOn, paceFor, pickV2Scenario, v2Run } from './v2';
import { STAGES } from '@/lib/stages';
import type { RunTransport } from '@/hooks/useRun';
import type { StreamHandle } from '@/lib/sse';
import type { AnswerEnvelope } from '@/types/envelope';
import type { StepId } from '@/types/events';
import type { RunEvent } from '@/lib/sse';

/** How long each stage appears to take, in ms of wall clock. */
const PACE: Record<StepId, number> = {
  '1': 220,
  '2': 320,
  '7': 520,
  '9': 640,
  '11': 480,
  '12': 300,
  '14': 360,
};

const SUMMARY: Record<StepId, (scenario: MockScenario) => string> = {
  '1': (scenario) =>
    scenario.status === 'blocked'
      ? 'The request was blocked by the ingress guard.'
      : 'The request passed the ingress guard.',
  '2': (scenario) =>
    `Routed as ${scenario.envelope.route.labels[0] ?? 'lookup'} with confidence ${scenario.envelope.route.confidence.toFixed(2)}.`,
  '7': () => 'The governed SQL path finished.',
  '9': (scenario) =>
    `Completed ${scenario.envelope.queries.length} query(s) and ${
      scenario.envelope.evidence.filter((block) => block.module !== 'lookup').length
    } analyst module(s).`,
  '11': (scenario) =>
    `Completed ${
      scenario.envelope.evidence.filter((block) => block.module !== 'lookup').length
    } typed analyst module(s).`,
  '12': (scenario) => `Approved ${scenario.envelope.claims.length} evidence claim(s).`,
  '14': () => 'The narrative passed numeric fact checking.',
};

function stepsFor(scenario: MockScenario): readonly StepId[] {
  return STAGES.filter((stage) => {
    if (stage.step === '7' || stage.step === '9') return scenario.stages.sql;
    if (stage.step === '11') return scenario.stages.analysts;
    return true;
  }).map((stage) => stage.step);
}

/** The plan a mock run follows, in order, with its own `seq` numbering. */
function plan(scenario: MockScenario, runId: string): readonly { delay: number; event: RunEvent }[] {
  const script: { delay: number; event: RunEvent }[] = [];
  let seq = 0;
  let clock = 180;
  const next = () => (seq += 1);

  for (const step of stepsFor(scenario)) {
    const stage = STAGES.find((candidate) => candidate.step === step);
    if (!stage) continue;
    const duration = PACE[step];

    script.push({
      delay: clock,
      event: {
        type: 'step_started',
        seq: next(),
        run_id: runId,
        step,
        component: stage.component,
        at: new Date().toISOString(),
      },
    });
    clock += duration;
    script.push({
      delay: clock,
      event: {
        type: 'step_finished',
        seq: next(),
        run_id: runId,
        step,
        component: stage.component,
        status: scenario.status === 'blocked' && step === '1' ? 'failed' : 'ok',
        duration_ms: duration,
        summary: SUMMARY[step](scenario),
      },
    });
    clock += 90;
  }

  // clarify is emitted before the terminal event, exactly as service.py does.
  if (scenario.envelope.clarification) {
    script.push({
      delay: clock,
      event: {
        type: 'clarify',
        seq: next(),
        run_id: runId,
        what_understood: scenario.envelope.clarification.what_understood,
        what_needs_clarification:
          scenario.envelope.clarification.what_needs_clarification,
      },
    });
    clock += 140;
  }

  if (scenario.status === 'error') {
    script.push({
      delay: clock,
      event: {
        type: 'error',
        seq: next(),
        run_id: runId,
        error: {
          code: 'internal',
          message: 'Run failed: the resolver could not bind the requested dimension.',
          retriable: false,
        },
      },
    });
  } else {
    script.push({
      delay: clock,
      event: {
        type: 'answer',
        seq: next(),
        run_id: runId,
        status: scenario.status,
      },
    });
  }

  return script;
}

type MockRun = { kind: 'v1'; scenario: MockScenario } | { kind: 'v2'; id: string };

export function mockTransport(): RunTransport {
  const runs = new Map<string, MockRun>();
  let counter = 0;

  return {
    ask: async (question, clarificationOf, options = {}) => {
      const previous = clarificationOf ? runs.get(clarificationOf) : undefined;
      // A reply to a V2 clarification follows the captured clarify flow; any
      // other question is matched to a V2 capture first, then to the V1 samples.
      const v2Id =
        previous?.kind === 'v2' && previous.id.startsWith('clarify-v2')
          ? clarifyFollowOn(previous.id, options.optionId ?? null)
          : pickV2Scenario(question);
      const run: MockRun = v2Id ? { kind: 'v2', id: v2Id } : { kind: 'v1', scenario: pickScenario(question) };
      const tag = run.kind === 'v2' ? `v2-${run.id}` : run.scenario.id;
      const runId = `mock-${(counter += 1).toString().padStart(4, '0')}-${tag}`;
      runs.set(runId, run);
      // A little latency, so the submitting state is actually visible.
      await new Promise((resolve) => window.setTimeout(resolve, 180));
      return runId;
    },

    stream: (runId, handlers): StreamHandle => {
      const run = runs.get(runId);
      if (!run) {
        handlers.onTransportError(false);
        return { close: () => {} };
      }

      const timers: number[] = [];
      let closed = false;
      const schedule = (script: readonly { delay: number; event: RunEvent }[]) => {
        for (const { delay, event } of script) {
          timers.push(
            window.setTimeout(() => {
              handlers.onEvent(event);
              if (event.type === 'answer' || event.type === 'error') handlers.onComplete();
            }, delay),
          );
        }
      };

      if (run.kind === 'v1') {
        schedule(plan(run.scenario, runId));
      } else {
        // The captured V2 stream, replayed in order at a readable pace.
        void v2Run(run.id, runId).then((captured) => {
          if (closed) return;
          if (!captured) {
            handlers.onTransportError(false);
            return;
          }
          let clock = 180;
          schedule(
            captured.events.map((event) => {
              const delay = clock;
              clock += paceFor(event);
              return { delay, event };
            }),
          );
        });
      }
      return {
        close: () => {
          closed = true;
          timers.forEach((timer) => window.clearTimeout(timer));
        },
      };
    },

    getRun: async (runId): Promise<AnswerEnvelope> => {
      const run = runs.get(runId) ?? { kind: 'v1', scenario: MOCK_SCENARIOS[0]! };
      // Stand in for the one 202-then-retry the real endpoint usually costs.
      await new Promise((resolve) => window.setTimeout(resolve, 420));
      if (run.kind === 'v2') {
        const captured = await v2Run(run.id, runId);
        if (captured) return captured.envelope as unknown as AnswerEnvelope;
      }
      const scenario = run.kind === 'v1' ? run.scenario : MOCK_SCENARIOS[0]!;
      return { ...scenario.envelope, run_id: runId };
    },
  };
}
