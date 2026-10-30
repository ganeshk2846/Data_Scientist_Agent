/**
 * Suggested follow-up questions.
 *
 * Hard rule: a follow-up must be a question this backend can actually answer,
 * and must contain no number, claim or insight of our own. Every suggestion is
 * a template filled from `scope.metric` and `scope.window` only — the same two
 * patterns proven by the verified suggestion chips:
 *
 *   lookup     "What was <metric> in <period>?"
 *   anomaly    "Was <metric> unusual in <period>?"     (needs metric + year)
 *   compare    "How did <metric> in <year> compare to <year-1>?"
 *
 * The router needs a governed metric AND an explicit window including the year;
 * without both it clarifies instead. So when the scope does not give us both,
 * we return nothing rather than offer a question that will not answer.
 */

import { METRIC_PHRASE, MONTHS, isGovernedMetric } from './metrics';
import type { AnswerEnvelope } from './../types/envelope';

interface Period {
  /** "August 2018" or "2018" — a phrase the router's extractor accepts. */
  phrase: string;
  year: number;
  /** Null for a whole-year window. */
  monthIndex: number | null;
}

/**
 * Reads `scope.window`, an ISO half-open interval, into a phrase. Only exact
 * calendar months and exact calendar years are recognised: a partial window
 * cannot be restated as a phrase without distorting it.
 */
function readPeriod(window: string | null): Period | null {
  if (!window) return null;
  const parts = window.split('/');
  if (parts.length !== 2) return null;
  const start = new Date(`${parts[0]}T00:00:00Z`);
  const end = new Date(`${parts[1]}T00:00:00Z`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null;
  if (start.getUTCDate() !== 1 || end.getUTCDate() !== 1) return null;

  const months =
    (end.getUTCFullYear() - start.getUTCFullYear()) * 12 +
    (end.getUTCMonth() - start.getUTCMonth());
  const year = start.getUTCFullYear();

  if (months === 1) {
    return {
      phrase: `${MONTHS[start.getUTCMonth()]} ${year}`,
      year,
      monthIndex: start.getUTCMonth(),
    };
  }
  if (months === 12 && start.getUTCMonth() === 0) {
    return { phrase: String(year), year, monthIndex: null };
  }
  return null;
}

export interface FollowUp {
  question: string;
  /** Why this is being offered — shown as a quiet caption. */
  kind: 'anomaly' | 'compare' | 'lookup';
}

/**
 * Up to three follow-ups, ordered so the one that opens a different kind of
 * analysis comes first. Returns an empty list whenever the scope cannot
 * support a question the backend will answer.
 */
export function buildFollowUps(envelope: AnswerEnvelope): readonly FollowUp[] {
  if (envelope.status !== 'answered') return [];

  const metricId = envelope.scope?.metric?.toLowerCase() ?? null;
  if (!metricId || !isGovernedMetric(metricId)) return [];
  const metric = METRIC_PHRASE[metricId];

  const period = readPeriod(envelope.scope?.window ?? null);
  if (!period) return [];

  const routes = new Set(envelope.route?.labels ?? []);
  const out: FollowUp[] = [];

  // If this run was a plain lookup, the interesting next step is diagnostic.
  if (!routes.has('anomaly')) {
    out.push({
      question: `Was ${metric} unusual in ${period.phrase}?`,
      kind: 'anomaly',
    });
  }

  // Year-over-year comparison. The comparative path handled "compare" fine.
  out.push({
    question: `How did ${metric} in ${period.year} compare to ${period.year - 1}?`,
    kind: 'compare',
  });

  // The neighbouring period, as a straight lookup.
  if (period.monthIndex !== null) {
    const previous = period.monthIndex === 0 ? 11 : period.monthIndex - 1;
    const previousYear = period.monthIndex === 0 ? period.year - 1 : period.year;
    out.push({
      question: `What was ${metric} in ${MONTHS[previous]} ${previousYear}?`,
      kind: 'lookup',
    });
  } else {
    out.push({
      question: `What was ${metric} in ${period.year - 1}?`,
      kind: 'lookup',
    });
  }

  // An anomaly run has already answered the diagnostic question, so offer the
  // month-level view instead when we have a year-level scope.
  if (routes.has('anomaly') && period.monthIndex === null) {
    out.push({
      question: `Was ${metric} unusual in December ${period.year}?`,
      kind: 'anomaly',
    });
  }

  return out.slice(0, 3);
}

export const FOLLOW_UP_CAPTION: Record<FollowUp['kind'], string> = {
  anomaly: 'Diagnostic',
  compare: 'Comparative',
  lookup: 'Lookup',
};
