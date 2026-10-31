import { Check, CircleSlash, Loader2, Minus } from 'lucide-react';

import { Tag } from './StatusBadge';
import { Card, SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import { formatDuration } from '@/lib/format';
import type { PlanStepProgress } from '@/lib/runState';
import { TYPICAL_MODEL_SECONDS, isLiveModel, stepBadge } from '@/lib/v2';

/**
 * The decomposed plan as a checklist (Track 5, item 5).
 *
 * Live, each step lights up as its `plan_step_started` event arrives; settled,
 * it is rebuilt from `plan` + `step_results`. Following the jewellery rule,
 * only the step that is running wears the accent; finished steps are ink.
 * Durations are the backend's `duration_ms`, printed verbatim — no total.
 */
export function PlanView({
  steps,
  live,
}: {
  steps: readonly PlanStepProgress[];
  live: boolean;
}) {
  if (steps.length === 0) return null;

  return (
    <Card tone="sunken" className="px-5 py-5 sm:px-7" as="section">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <SectionLabel>The plan</SectionLabel>
        <span className="text-[0.6875rem] text-ink-faint">
          {steps.length} {steps.length === 1 ? 'step' : 'steps'}
          {live ? ' · running' : ''}
        </span>
      </div>
      <ol className="mt-4 space-y-3" aria-live={live ? 'polite' : undefined}>
        {steps.map((step) => {
          const running = step.state === 'running';
          const done = step.state === 'ok' || step.state === 'empty';
          const failed = step.state === 'error' || step.state === 'refused' || step.state === 'insufficient_evidence';
          const typical = TYPICAL_MODEL_SECONDS[step.tool];
          return (
            <li
              key={step.stepId}
              className="grid grid-cols-[1.25rem_1fr] gap-x-3"
              data-plan-step={step.stepId}
              data-state={step.state}
            >
              <span
                aria-hidden
                className={cx(
                  'mt-0.5 flex h-4 w-4 items-center justify-center rounded-full border',
                  running
                    ? 'border-accent text-accent'
                    : done
                      ? 'border-ink bg-ink text-bg'
                      : failed
                        ? 'border-terracotta text-terracotta'
                        : 'border-hairline-strong text-ink-faint',
                )}
              >
                {running ? (
                  <Loader2 size={10} strokeWidth={2} className="motion-safe:animate-spin" />
                ) : done ? (
                  <Check size={10} strokeWidth={2.5} />
                ) : failed ? (
                  <CircleSlash size={10} strokeWidth={2} />
                ) : step.state === 'skipped' ? (
                  <Minus size={10} strokeWidth={2} />
                ) : null}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  <span className="font-mono text-[0.6875rem] text-ink-faint">{step.stepId}</span>
                  <Tag tone={running ? 'accent' : 'neutral'}>{stepBadge(step.tool)}</Tag>
                  <span className="sr-only">
                    {running ? 'running' : step.state === 'pending' ? 'waiting' : step.state}
                  </span>
                  {step.durationMs !== null && !running ? (
                    <span className="text-[0.6875rem] tabular-nums text-ink-faint">
                      {formatDuration(step.durationMs)}
                    </span>
                  ) : null}
                </div>
                <p
                  className={cx(
                    'mt-1.5 max-w-prose text-small leading-relaxed',
                    step.state === 'pending' ? 'text-ink-faint' : 'text-ink-muted',
                  )}
                >
                  {step.purpose}
                </p>
                {running && (step.modelRunning || isLiveModel(step.tool)) && typical ? (
                  <p className="mt-1 text-[0.75rem] text-ink-muted">
                    Running model — this can take ~{typical} s
                  </p>
                ) : null}
                {!running && step.summary && step.state !== 'pending' ? (
                  <p className="mt-1 max-w-prose text-[0.75rem] leading-relaxed text-ink-faint">
                    {step.summary}
                  </p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
