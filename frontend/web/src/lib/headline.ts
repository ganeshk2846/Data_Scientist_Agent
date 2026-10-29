/**
 * The one figure a briefing leads with.
 *
 * SAFE-8: this *locates* a figure the envelope already states. It never sums,
 * averages, picks a maximum, or rounds. There are exactly two places an
 * envelope states a single headline number, and this reads them in order:
 *
 *   1. a `lookup` block that returned exactly one row and one column — the
 *      figure IS that cell, and its unit IS that column's name;
 *   2. an `anomaly` result's `actual` — the value under test, as the backend
 *      reported it.
 *
 * When the envelope leads with a table, a chart or nothing at all, this returns
 * null and the caller must say so rather than invent a figure to show.
 */

import { asAnomalyResult, asLookup } from './evidence';
import { formatWindow, humanise } from './format';
import { asHeroFigure } from './evidenceTitle';
import type { AnswerEnvelope } from '@/types/envelope';

export interface Headline {
  value: number;
  /** The column name, or the metric — whichever the envelope gave us. */
  unit: string;
  /** `scope.metric`, humanised, when the envelope set one. */
  metric: string | null;
  /** `scope.window`, as a readable period, when the envelope set one. */
  period: string | null;
  /** Which of the two sources above this came from, for the caption. */
  source: 'lookup' | 'anomaly';
}

export function readHeadline(envelope: AnswerEnvelope): Headline | null {
  const metric = envelope.scope.metric ? humanise(envelope.scope.metric) : null;
  const period = formatWindow(envelope.scope.window);

  for (const block of envelope.evidence) {
    const lookup = asLookup(block);
    if (!lookup) continue;
    const hero = asHeroFigure(lookup);
    if (hero) {
      return { value: hero.value, unit: hero.unit, metric, period, source: 'lookup' };
    }
  }

  for (const block of envelope.evidence) {
    const anomaly = asAnomalyResult(block);
    if (!anomaly) continue;
    return {
      value: anomaly.actual,
      unit: metric ?? 'actual',
      metric,
      period: period ?? formatWindow(anomaly.window) ?? anomaly.window,
      source: 'anomaly',
    };
  }

  return null;
}
