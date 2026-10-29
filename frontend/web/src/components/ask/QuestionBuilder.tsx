import { ArrowRight, ChevronRight, Info } from 'lucide-react';
import { useId, useMemo, useState } from 'react';

import { Hairline, SectionLabel } from '@/components/ui/Card';
import { Segmented } from '@/components/ui/Segmented';
import { cx } from '@/lib/cx';
import {
  ANALYSES,
  BUILDER_PERIODS,
  DEFAULT_BUILDER,
  composeQuestion,
  comparisonCaveat,
  findPeriod,
  type BuilderState,
} from '@/lib/builder';
import { GOVERNED_METRICS, METRIC_LABEL } from '@/lib/metrics';

/**
 * The guided question builder.
 *
 * Optional: it sits collapsed under the ask box and opens on request, because
 * typing is still the fastest way in for anyone who knows what they want. What
 * it offers is *certainty* — every combination of the three pickers composes
 * one of the three question patterns verified against the live backend, so a
 * built question cannot come back as a clarification.
 *
 * The live preview is the point. The reader sees the English sentence the
 * backend is about to receive, in the same serif the answer will be set in, and
 * can read it before committing.
 */
export function QuestionBuilder({
  onAsk,
  disabled = false,
}: {
  onAsk: (question: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<BuilderState>(DEFAULT_BUILDER);
  const panelId = useId();

  const question = useMemo(() => composeQuestion(state), [state]);
  const caveat = comparisonCaveat(state);
  const period = findPeriod(state.periodId);

  return (
    <div className="rounded-sm border border-hairline bg-[rgb(var(--c-surface)/0.5)]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-hover ease-editorial hover:bg-[rgb(var(--c-hairline)/0.3)]"
      >
        <ChevronRight
          size={14}
          strokeWidth={1.5}
          aria-hidden
          className={cx(
            'shrink-0 text-ink-faint transition-transform duration-micro ease-editorial',
            open && 'rotate-90',
          )}
        />
        <span className="min-w-0 flex-1 text-[0.8125rem] leading-5 text-ink-muted">
          Build a question
        </span>
        <span className="shrink-0 text-micro uppercase tracking-label text-ink-faint">
          {open ? 'Close' : 'Optional'}
        </span>
      </button>

      {open ? (
        <div id={panelId} className="border-t border-hairline px-4 pb-4 pt-5 sm:px-5">
          <div className="space-y-5">
            <div>
              <SectionLabel className="mb-2.5">Metric</SectionLabel>
              <Segmented
                label="Metric"
                value={state.metric}
                options={GOVERNED_METRICS.map((metric) => ({
                  value: metric,
                  label: METRIC_LABEL[metric],
                }))}
                onChange={(metric) => setState((current) => ({ ...current, metric }))}
                className="flex-wrap"
              />
            </div>

            <div>
              <SectionLabel className="mb-2.5">Period</SectionLabel>
              {/* Twenty-six periods is too many for a segmented row, so this
                  one is a real select — a native menu is faster than a grid of
                  chips, and it keeps the three pickers on one visual rail. */}
              <div className="relative inline-flex">
                <select
                  value={state.periodId}
                  onChange={(event) =>
                    setState((current) => ({ ...current, periodId: event.target.value }))
                  }
                  aria-label="Period"
                  className={cx(
                    'appearance-none rounded-sm border border-hairline bg-sunken py-1.5 pl-3 pr-9',
                    'text-[0.8125rem] leading-5 text-ink transition-colors duration-hover ease-editorial',
                    'hover:border-hairline-strong',
                  )}
                >
                  <optgroup label="Whole year">
                    {BUILDER_PERIODS.filter((item) => item.monthIndex === null).map(
                      (item) => (
                        <option key={item.id} value={item.id}>
                          {item.phrase}
                        </option>
                      ),
                    )}
                  </optgroup>
                  <optgroup label="Month">
                    {BUILDER_PERIODS.filter((item) => item.monthIndex !== null).map(
                      (item) => (
                        <option key={item.id} value={item.id}>
                          {item.phrase}
                        </option>
                      ),
                    )}
                  </optgroup>
                </select>
                <ChevronRight
                  size={13}
                  strokeWidth={1.5}
                  aria-hidden
                  className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rotate-90 text-ink-faint"
                />
              </div>
              <p className="mt-2 text-[0.6875rem] leading-4 text-ink-faint">
                Complete calendar periods only, and always with the year — the
                router clarifies rather than guessing a year.
              </p>
            </div>

            <div>
              <SectionLabel className="mb-2.5">Analysis</SectionLabel>
              <Segmented
                label="Analysis"
                value={state.analysis}
                options={ANALYSES}
                onChange={(analysis) => setState((current) => ({ ...current, analysis }))}
                className="flex-wrap"
              />
            </div>

            {/* The absence of a dimensional breakdown is a decision, so it is
                stated rather than silently missing. */}
            <div className="flex items-start gap-2.5 rounded-sm bg-sunken px-3 py-2.5">
              <Info
                size={13}
                strokeWidth={1.5}
                aria-hidden
                className="mt-0.5 shrink-0 text-ink-faint"
              />
              <p className="text-[0.6875rem] leading-4 text-ink-faint">
                <span className="text-ink-muted">No breakdown picker.</span> A question
                naming a dimension routes to driver attribution, and that path raises
                in the orchestrator today, so it is withheld rather than offered and
                failed.
              </p>
            </div>
          </div>

          <Hairline className="my-5" />

          {/* The preview: the actual sentence, in the answer's own serif. */}
          <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
            <div className="min-w-0 flex-1">
              <SectionLabel>The question</SectionLabel>
              <p className="opsz-title mt-2.5 max-w-prose font-serif text-[1.0625rem] leading-7 text-ink">
                {question}
              </p>
              {caveat ? (
                <p className="mt-2 text-[0.6875rem] leading-4 text-ink-faint">
                  {caveat}
                </p>
              ) : (
                <p className="mt-2 text-[0.6875rem] leading-4 text-ink-faint">
                  {period.phrase} · governed metric · verified pattern
                </p>
              )}
            </div>

            <button
              type="button"
              onClick={() => onAsk(question)}
              disabled={disabled}
              className={cx(
                'inline-flex shrink-0 items-center gap-2 rounded-sm border border-accent bg-accent',
                'px-4 py-2 text-[0.8125rem] font-medium text-on-accent',
                'transition-[filter] duration-hover ease-editorial hover:brightness-[1.06]',
                'disabled:cursor-not-allowed disabled:opacity-45',
              )}
            >
              Ask
              <ArrowRight size={14} strokeWidth={1.5} aria-hidden />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
