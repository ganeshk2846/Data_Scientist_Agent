/**
 * The guided question builder.
 *
 * Three pickers — metric, period, analysis — that assemble one natural English
 * sentence. The builder is deliberately *narrow*: it can only produce the three
 * question patterns verified to return a full briefing against the live
 * backend, which are the same three the hero chips use.
 *
 *   lookup      "What was <metric> in <period>?"
 *   anomaly     "Was <metric> unusual in <period>?"
 *   comparison  "How did <metric> in <year> compare to <year−1>?"
 *
 * There is NO dimensional breakdown, and that is a decision rather than an
 * omission: a question naming a dimension routes to `driver`, and the driver
 * path raises inside the orchestrator (CLAUDE.md gap 14), so every one of those
 * questions comes back as an error. The builder says so in the interface rather
 * than offering a picker that can only disappoint.
 *
 * SAFE-8: nothing here touches a figure. The builder composes a *question*,
 * from a closed vocabulary, and the backend answers it.
 */

import { METRIC_PHRASE, MONTHS, type GovernedMetric } from './metrics';

export type Analysis = 'lookup' | 'anomaly' | 'compare';

/**
 * The periods on offer. The dataset is the Brazilian e-commerce public set,
 * whose complete calendar years are 2017 and 2018 — a window outside the data
 * answers with nothing, so the picker does not offer one.
 */
export interface BuilderPeriod {
  id: string;
  /** The phrase the extractor reads. Always carries the year. */
  phrase: string;
  /** How the picker labels it. */
  label: string;
  year: number;
  /** Null for a whole calendar year. */
  monthIndex: number | null;
}

export const BUILDER_YEARS = [2017, 2018] as const;

function monthPeriod(year: number, monthIndex: number): BuilderPeriod {
  const month = MONTHS[monthIndex] ?? 'January';
  return {
    id: `${year}-${String(monthIndex + 1).padStart(2, '0')}`,
    phrase: `${month} ${year}`,
    label: `${month.slice(0, 3)} ${year}`,
    year,
    monthIndex,
  };
}

export const BUILDER_PERIODS: readonly BuilderPeriod[] = [
  ...BUILDER_YEARS.map((year) => ({
    id: String(year),
    phrase: String(year),
    label: String(year),
    year,
    monthIndex: null,
  })),
  ...BUILDER_YEARS.flatMap((year) =>
    MONTHS.map((_, monthIndex) => monthPeriod(year, monthIndex)),
  ),
];

export const ANALYSES: readonly {
  value: Analysis;
  label: string;
  note: string;
}[] = [
  { value: 'lookup', label: 'Value', note: 'What the figure was' },
  { value: 'anomaly', label: 'Unusual?', note: 'Against a seasonal baseline' },
  { value: 'compare', label: 'Against last year', note: 'The same metric, year on year' },
];

export interface BuilderState {
  metric: GovernedMetric;
  periodId: string;
  analysis: Analysis;
}

export const DEFAULT_BUILDER: BuilderState = {
  metric: 'revenue',
  periodId: '2018-08',
  analysis: 'lookup',
};

export function findPeriod(periodId: string): BuilderPeriod {
  return (
    BUILDER_PERIODS.find((period) => period.id === periodId) ??
    BUILDER_PERIODS[0] ?? {
      id: '2018',
      phrase: '2018',
      label: '2018',
      year: 2018,
      monthIndex: null,
    }
  );
}

/**
 * The sentence. One of exactly three templates, filled from the closed
 * vocabulary — so whatever the reader picks, the result is a question this
 * backend is known to answer.
 */
export function composeQuestion(state: BuilderState): string {
  const metric = METRIC_PHRASE[state.metric];
  const period = findPeriod(state.periodId);

  switch (state.analysis) {
    case 'anomaly':
      return `Was ${metric} unusual in ${period.phrase}?`;
    case 'compare':
      return `How did ${metric} in ${period.year} compare to ${period.year - 1}?`;
    case 'lookup':
      return `What was ${metric} in ${period.phrase}?`;
  }
}

/**
 * A comparison is stated at year level — `scope` can only carry one window, so
 * a month-level comparison would need a window the envelope cannot describe.
 * The builder says this out loud when the picked period is a month.
 */
export function comparisonCaveat(state: BuilderState): string | null {
  if (state.analysis !== 'compare') return null;
  const period = findPeriod(state.periodId);
  if (period.monthIndex === null) return null;
  return `Compared at year level: ${period.year} against ${period.year - 1}.`;
}
