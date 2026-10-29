/**
 * The governed vocabulary — the only metrics and period shapes the router will
 * answer on, and the only phrases we are allowed to put in a question we
 * compose for the reader.
 *
 * Shared by `followUps.ts` (which fills templates from an answered run's scope)
 * and `builder.ts` (which lets the reader assemble one from pickers). Both are
 * bound by the same two rules, learned from probing the live backend:
 *
 *   - the question must name a metric the governed registry covers;
 *   - the window must be explicit AND include the year, or the router
 *     clarifies instead of answering.
 */

/** The metrics the governed registry covers. Anything else is not answerable. */
export const GOVERNED_METRICS = ['gmv', 'revenue', 'order_count', 'aov'] as const;

export type GovernedMetric = (typeof GOVERNED_METRICS)[number];

export const GOVERNED = new Set<string>(GOVERNED_METRICS);

/** How each metric is said in a sentence. The extractor reads these forms. */
export const METRIC_PHRASE: Record<GovernedMetric, string> = {
  gmv: 'GMV',
  revenue: 'revenue',
  order_count: 'order count',
  aov: 'average order value',
};

/** How each metric is labelled in the interface. */
export const METRIC_LABEL: Record<GovernedMetric, string> = {
  gmv: 'GMV',
  revenue: 'Revenue',
  order_count: 'Order count',
  aov: 'Average order value',
};

export const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
] as const;

export function isGovernedMetric(value: string): value is GovernedMetric {
  return GOVERNED.has(value);
}
