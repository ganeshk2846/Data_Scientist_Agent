/**
 * Sample `AnswerEnvelope`s, one per `RunStatus`, for `?mock=1`.
 *
 * These are contract-accurate: the shapes, literal unions and field names match
 * `contracts/models.py` exactly, and the numbers are consistent with the real
 * Brazilian e-commerce snapshot. This is the only place `next_actions` and
 * `refusal.closest_answerable` are ever populated — `build_answer_envelope`
 * hardcodes the former to `()` and never sets the latter, so mock mode is how
 * those designs stay reviewable.
 */

import type {
  AnswerEnvelope,
  Provenance,
  RunStatus,
} from '@/types/envelope';

const PROVENANCE: Provenance = {
  model_name: 'none',
  model_version: '',
  commit: '',
  snapshot_id: 'brazil-ecommerce',
  catalog_version: '79f9da2e6b1d34cf',
  timestamp: '2018-09-02T09:14:22.418Z',
};

function base(runId: string, status: RunStatus): AnswerEnvelope {
  return {
    contract_version: '1.0.0',
    run_id: runId,
    status,
    route: { labels: ['lookup'], confidence: 0.9, reason: '', },
    conclusion: null,
    scope: {
      metric: null,
      window: null,
      filters: [],
      grain: null,
      data_range: null,
      governed: false,
    },
    evidence: [],
    claims: [],
    method: [],
    queries: [],
    caveats: [],
    causal_boundary_note: null,
    next_actions: [],
    clarification: null,
    refusal: null,
    block: null,
    run_metrics: { latency_ms: 0, tokens: 0, queries: 0, rows: 0, retries: 0 },
    provenance: PROVENANCE,
  };
}

/* ---------- answered: a governed lookup ---------- */

const LOOKUP: AnswerEnvelope = {
  ...base('mock-lookup-6512', 'answered'),
  route: {
    labels: ['lookup'],
    confidence: 0.9,
    reason:
      'The catalog keywords and the governed registry identify a lookup with enough confidence to answer directly.',
  },
  conclusion: 'The governed result is 6,512.',
  scope: {
    metric: 'order_count',
    window: '2018-08-01/2018-09-01',
    filters: [],
    grain: 'month',
    data_range: null,
    governed: true,
  },
  evidence: [
    {
      module: 'lookup',
      output: {
        query_id: 'Q1',
        columns: [{ name: 'order_count', type: 'integer' }],
        rows: [[6512]],
        row_count: 1,
        truncated: false,
      },
      source_claims: ['C1'],
    },
  ],
  claims: [
    {
      claim_id: 'C1',
      text: 'The governed query Q1 supplied the cited numeric values.',
      numbers: [
        { token: '6,512', value: 6512, unit: null },
        { token: '1', value: 1, unit: null },
      ],
      source: { type: 'query', id: 'Q1' },
      grade: 1,
      kind: 'fact',
    },
  ],
  method: [{ name: 'governed_sql', params: { queries: 1 } }],
  queries: [
    {
      query_id: 'Q1',
      sql: `SELECT
  COUNT(DISTINCT o.order_id) AS order_count
FROM "orders" AS o
WHERE o.order_purchase_timestamp >= '2018-08-01'
  AND o.order_purchase_timestamp < '2018-09-01'
LIMIT 1`,
      status: 'ok',
      duration_ms: 93,
      rows_scanned: 99441,
      est_cost: null,
      origin: 'compiler',
      repair_of: null,
      validation_mode: 'enterprise',
    },
  ],
  run_metrics: { latency_ms: 101, tokens: 0, queries: 1, rows: 1, retries: 0 },
};

/* ---------- answered: anomaly with a sibling series ---------- */

const MONTHS: readonly (readonly [string, number])[] = [
  ['2017-09', 4285], ['2017-10', 4631], ['2017-11', 7544], ['2017-12', 5673],
  ['2018-01', 7269], ['2018-02', 6728], ['2018-03', 7211], ['2018-04', 6939],
  ['2018-05', 6873], ['2018-06', 6167], ['2018-07', 6292], ['2018-08', 6512],
];

const ANOMALY: AnswerEnvelope = {
  ...base('mock-anomaly-aug', 'answered'),
  route: {
    labels: ['anomaly'],
    confidence: 0.86,
    reason:
      'The question asks whether a period is unusual, which routes to the anomaly analyst over the governed series.',
  },
  conclusion:
    'August 2018 recorded 6,512 orders against an expected 6,744; the result is within the normal range, and the 3.4% shortfall does not clear the robust threshold.',
  scope: {
    metric: 'order_count',
    window: '2018-08-01/2018-09-01',
    filters: [],
    grain: 'month',
    data_range: '2016-09-01/2018-09-01',
    governed: true,
  },
  evidence: [
    {
      module: 'lookup',
      output: {
        query_id: 'Q1',
        columns: [
          { name: 'purchase_month', type: 'text' },
          { name: 'order_count', type: 'integer' },
        ],
        rows: MONTHS.map(([month, value]) => [month, value]),
        row_count: MONTHS.length,
        truncated: false,
      },
      source_claims: ['C1'],
    },
    {
      module: 'anomaly',
      output: {
        module: 'anomaly',
        status: 'ok',
        reason: null,
        result: {
          verdict: 'within_normal_range',
          window: 'August 2018',
          actual: 6512,
          expected: 6744,
          expected_range: [6038, 7450],
          deviation_pct: -3.44,
          robust_score: 0.82,
          persistence: 'one_off',
          threshold: 3.5,
          correction_used: null,
          calendar_effects: ['31-day month', 'no national holiday in window'],
          baseline_kind: 'seasonal',
        },
        parameters: { metric: 'order_count', grain: 'month', alpha: 0.05 },
        assumptions: [
          'The seasonal baseline uses month-of-year medians across two full years of history.',
          'A single period outside the band is reported as one_off until a second period confirms it.',
        ],
        sources: ['Q1'],
        artifacts: [],
      },
      source_claims: ['C2', 'C3'],
    },
  ],
  claims: [
    {
      claim_id: 'C1',
      text: 'The governed query Q1 supplied the monthly order series.',
      numbers: [{ token: '6,512', value: 6512, unit: null }],
      source: { type: 'query', id: 'Q1' },
      grade: 1,
      kind: 'fact',
    },
    {
      claim_id: 'C2',
      text: 'The anomaly analyst computed an expected value from the seasonal baseline.',
      numbers: [{ token: '6,744', value: 6744, unit: null }],
      source: { type: 'artifact', id: 'anomaly-1' },
      grade: 2,
      kind: 'consistent_with',
    },
    {
      claim_id: 'C3',
      text: 'The deviation does not clear the robust threshold for the window.',
      numbers: [{ token: '3.4%', value: -3.44, unit: 'percent' }],
      source: { type: 'artifact', id: 'anomaly-1' },
      grade: 2,
      kind: 'comparison',
    },
  ],
  method: [
    { name: 'governed_sql', params: { queries: 1 } },
    { name: 'anomaly', params: { grain: 'month', alpha: 0.05 } },
  ],
  queries: [
    {
      query_id: 'Q1',
      sql: `WITH monthly AS (
  SELECT
    strftime('%Y-%m', o.order_purchase_timestamp) AS purchase_month,
    COUNT(DISTINCT o.order_id) AS order_count
  FROM "orders" AS o
  WHERE o.order_purchase_timestamp >= '2016-09-01'
    AND o.order_purchase_timestamp < '2018-09-01'
  GROUP BY 1
)
SELECT purchase_month, order_count
FROM monthly
ORDER BY purchase_month
LIMIT 48`,
      status: 'ok',
      duration_ms: 412,
      rows_scanned: 99441,
      est_cost: null,
      origin: 'compiler',
      repair_of: null,
      validation_mode: 'enterprise',
    },
  ],
  caveats: [
    'The snapshot ends on 2018-09-03, so the final month is partial in the source data and has been excluded from the baseline.',
  ],
  run_metrics: { latency_ms: 486, tokens: 0, queries: 1, rows: 12, retries: 0 },
};

/* ---------- answered: driver attribution, with next actions ---------- */

const DRIVER: AnswerEnvelope = {
  ...base('mock-driver-freight', 'answered'),
  route: {
    labels: ['driver'],
    confidence: 0.78,
    reason:
      'A diagnostic question with a named metric and period routes to additive driver attribution.',
  },
  conclusion:
    'Revenue fell by 184,206.44 against the prior quarter. The largest contributor was SP, with an attributed change of −71,942.18, followed by RJ at −38,415.60.',
  scope: {
    metric: 'revenue',
    window: '2018-07-01/2018-10-01',
    filters: ['order_status=delivered'],
    grain: 'quarter',
    data_range: null,
    governed: true,
  },
  evidence: [
    {
      module: 'driver',
      output: {
        module: 'driver',
        status: 'ok',
        reason: null,
        result: {
          metric: 'revenue',
          current_period: 'Q3 2018',
          comparison_period: 'Q2 2018',
          total_change: -184206.44,
          drivers: [
            {
              dimension: 'customer_state',
              value: 'SP',
              contribution: -71942.18,
              share: 0.3905,
              interval: [-84310.5, -59573.86],
              sample_size: 14821,
              unstable: false,
              grade: 3,
              data_needed_to_strengthen: [],
            },
            {
              dimension: 'customer_state',
              value: 'RJ',
              contribution: -38415.6,
              share: 0.2086,
              interval: [-47002.14, -29829.06],
              sample_size: 5312,
              unstable: false,
              grade: 3,
              data_needed_to_strengthen: [],
            },
            {
              dimension: 'customer_state',
              value: 'MG',
              contribution: -21880.92,
              share: 0.1188,
              interval: [-28441.3, -15320.54],
              sample_size: 4190,
              unstable: false,
              grade: 2,
              data_needed_to_strengthen: [],
            },
            {
              dimension: 'customer_state',
              value: 'BA',
              contribution: 9432.77,
              share: 0.0512,
              interval: [1204.11, 17661.43],
              sample_size: 1188,
              unstable: false,
              grade: 2,
              data_needed_to_strengthen: [],
            },
            {
              dimension: 'customer_state',
              value: 'RR',
              contribution: -2104.35,
              share: 0.0114,
              interval: [-9880.42, 5671.72],
              sample_size: 27,
              unstable: true,
              grade: 1,
              data_needed_to_strengthen: [
                'More than 27 delivered orders in the period',
                'A second quarter of history for this state',
              ],
            },
          ],
          reconciliation_error: 0.31,
          candidates_examined: 27,
          correction_used: 'holm',
        },
        parameters: { metric: 'revenue', dimension: 'customer_state' },
        assumptions: [
          'Contributions are additive and decompose the total change exactly, up to the reported reconciliation error.',
          'Driver analysis is associational and is not causal evidence.',
        ],
        sources: ['Q1', 'Q2'],
        artifacts: [],
      },
      source_claims: ['C1', 'C2'],
    },
  ],
  claims: [
    {
      claim_id: 'C1',
      text: 'The governed queries supplied revenue by state for both periods.',
      numbers: [{ token: '184,206.44', value: -184206.44, unit: 'BRL' }],
      source: { type: 'query', id: 'Q1' },
      grade: 1,
      kind: 'fact',
    },
    {
      claim_id: 'C2',
      text: 'SP accounts for the largest share of the total change.',
      numbers: [
        { token: '−71,942.18', value: -71942.18, unit: 'BRL' },
        { token: '−38,415.60', value: -38415.6, unit: 'BRL' },
      ],
      source: { type: 'artifact', id: 'driver-1' },
      grade: 3,
      kind: 'concentration',
    },
  ],
  method: [
    { name: 'governed_sql', params: { queries: 2 } },
    { name: 'driver', params: { dimension: 'customer_state' } },
  ],
  queries: [
    {
      query_id: 'Q1',
      sql: `SELECT
  c.customer_state,
  SUM(oi.price + oi.freight_value) AS revenue
FROM "orders" AS o
JOIN "order_items" AS oi ON oi.order_id = o.order_id
JOIN "customers" AS c ON c.customer_id = o.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2018-07-01'
  AND o.order_purchase_timestamp < '2018-10-01'
GROUP BY c.customer_state
ORDER BY revenue DESC
LIMIT 50`,
      status: 'ok',
      duration_ms: 788,
      rows_scanned: 112650,
      est_cost: 41.8,
      origin: 'compiler',
      repair_of: null,
      validation_mode: 'enterprise',
    },
    {
      query_id: 'Q2',
      sql: `SELECT
  c.customer_state,
  SUM(oi.price + oi.freight_value) AS revenue
FROM "orders" AS o
JOIN "order_items" AS oi ON oi.order_id = o.order_id
JOIN "customers" AS c ON c.customer_id = o.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2018-04-01'
  AND o.order_purchase_timestamp < '2018-07-01'
GROUP BY c.customer_state
ORDER BY revenue DESC
LIMIT 50`,
      status: 'ok',
      duration_ms: 741,
      rows_scanned: 112650,
      est_cost: 41.2,
      origin: 'compiler',
      repair_of: null,
      validation_mode: 'enterprise',
    },
  ],
  caveats: [
    'The reconciler flagged a join fan-out of 1.13 between orders and order_items; revenue is summed at item grain and deduplicated by order.',
    'RR carries 27 delivered orders in the period and its contribution is reported as unstable.',
  ],
  causal_boundary_note:
    'Driver analysis is associational evidence, not proof that a dimension caused the change.',
  next_actions: [
    {
      action_id: 'A1',
      title: 'Review carrier performance on the SP–interior lanes',
      rank: 1,
      assumptions: [
        'The SP decline is concentrated in orders with freight above the 75th percentile.',
        'Carrier assignment did not change inside the quarter.',
      ],
      trade_offs: [
        'Renegotiating lane rates takes a full quarter to show in delivered revenue.',
        'Shifting carriers risks a short-term rise in late deliveries.',
      ],
      sensitivity:
        'If the freight split is driven by fewer than 500 orders, the ranking against RJ is no longer stable.',
      monitor: [
        'Weekly delivered revenue for SP',
        'Median days from purchase to delivery on SP lanes',
      ],
      data_that_would_change_ranking: [
        'Per-carrier cost at lane grain',
        'Seller-side stockout records for the period',
      ],
      kind: 'intervention',
    },
    {
      action_id: 'A2',
      title: 'Confirm whether the RJ decline is category-driven before acting',
      rank: 2,
      assumptions: ['Category mix is available at order-item grain for both quarters.'],
      trade_offs: ['A decomposition run costs one additional governed query budget.'],
      sensitivity: 'A category-level split would move RJ above SP if concentration exceeds 0.6.',
      monitor: ['RJ revenue by product category, monthly'],
      data_that_would_change_ranking: ['Category-level price changes inside the quarter'],
      kind: 'information_gathering',
    },
  ],
  run_metrics: { latency_ms: 1642, tokens: 0, queries: 2, rows: 54, retries: 0 },
};

/* ---------- the non-answered statuses ---------- */

const CLARIFY: AnswerEnvelope = {
  ...base('mock-clarify-revenue', 'clarify'),
  route: {
    labels: ['clarify'],
    confidence: 0.5,
    reason: 'A diagnostic route is explicit, but the metric or time window is incomplete.',
  },
  clarification: {
    what_understood: 'You are asking about the governed metric Revenue (revenue).',
    what_needs_clarification:
      'Please specify the time period to diagnose, such as a month, quarter or year.',
  },
};

const REFUSED: AnswerEnvelope = {
  ...base('mock-refused-churn', 'refused'),
  route: {
    labels: ['refused'],
    confidence: 0.81,
    reason: 'The request asks for a forward-looking risk score, which the registry does not govern.',
  },
  refusal: {
    missing: [
      'No governed metric covers per-account churn risk in this snapshot.',
      'The snapshot has no subscription or account lifecycle table to define churn against.',
    ],
    // Never set by the live backend; populated here so the design is reviewable.
    closest_answerable:
      'How many customers placed a repeat order between January and August 2018?',
  },
};

const BLOCKED: AnswerEnvelope = {
  ...base('mock-blocked-drop', 'blocked'),
  route: {
    labels: ['blocked'],
    confidence: 1,
    reason: 'The ingress guard matched a data-definition token.',
  },
  block: {
    reason: 'write_attempt',
    detail:
      'The request contained the token DROP TABLE, which the ingress guard rejects before routing. The gateway is read-only at the driver level, so no write could have executed in any case.',
  },
};

const INSUFFICIENT: AnswerEnvelope = {
  ...base('mock-insufficient-rr', 'insufficient_evidence'),
  route: {
    labels: ['anomaly'],
    confidence: 0.74,
    reason: 'An anomaly route was selected, but the series is too short to baseline.',
  },
  conclusion:
    'The series holds 4 periods for this segment, below the 8 required for a robust baseline, so no verdict is reported.',
  caveats: [
    'A robust trailing baseline needs at least 8 periods; 4 were available.',
    'Seasonal baselining needs two full years of history, which this segment does not have.',
  ],
  method: [{ name: 'governed_sql', params: { queries: 1 } }],
  run_metrics: { latency_ms: 318, tokens: 0, queries: 1, rows: 4, retries: 0 },
};

const ERROR: AnswerEnvelope = {
  ...base('mock-error-internal', 'error'),
  // _error_envelope stamps this false "blocked" label; the UI suppresses the
  // route strip for status === 'error' rather than repeat it.
  route: {
    labels: ['blocked'],
    confidence: 0,
    reason: 'Run failed: the resolver could not bind the requested dimension.',
  },
  caveats: ['Run failed: the resolver could not bind the requested dimension.'],
};

export interface MockScenario {
  id: string;
  question: string;
  status: RunStatus;
  envelope: AnswerEnvelope;
  /** Which conditional stages this run should light up. */
  stages: { sql: boolean; analysts: boolean };
}

export const MOCK_SCENARIOS: readonly MockScenario[] = [
  {
    id: 'lookup',
    question: 'How many orders were there in August 2018?',
    status: 'answered',
    envelope: LOOKUP,
    stages: { sql: true, analysts: false },
  },
  {
    id: 'anomaly',
    question: 'Was August 2018 unusual for orders?',
    status: 'answered',
    envelope: ANOMALY,
    stages: { sql: true, analysts: true },
  },
  {
    id: 'driver',
    question: 'Why did revenue drop in Q3 2018?',
    status: 'answered',
    envelope: DRIVER,
    stages: { sql: true, analysts: true },
  },
  {
    id: 'clarify',
    question: 'Why did revenue drop in August?',
    status: 'clarify',
    envelope: CLARIFY,
    stages: { sql: false, analysts: false },
  },
  {
    id: 'refused',
    question: 'Which accounts have elevated churn risk next quarter?',
    status: 'refused',
    envelope: REFUSED,
    stages: { sql: false, analysts: false },
  },
  {
    id: 'blocked',
    question: 'DROP TABLE orders; then show me revenue',
    status: 'blocked',
    envelope: BLOCKED,
    stages: { sql: false, analysts: false },
  },
  {
    id: 'insufficient',
    question: 'Is Roraima unusual for order volume?',
    status: 'insufficient_evidence',
    envelope: INSUFFICIENT,
    stages: { sql: true, analysts: true },
  },
  {
    id: 'error',
    question: 'Revenue by state last quarter',
    status: 'error',
    envelope: ERROR,
    stages: { sql: true, analysts: false },
  },
];

/**
 * Picks the scenario a question should resolve to. Matching is on intent words
 * so the suggestion chips and free typing both land somewhere sensible.
 */
export function pickScenario(question: string): MockScenario {
  const text = question.toLowerCase();
  const byId = (id: string) => MOCK_SCENARIOS.find((scenario) => scenario.id === id);

  if (/\bdrop table\b|\bdelete\b|\btruncate\b|\binsert\b|\bupdate\b/.test(text)) {
    return byId('blocked') ?? MOCK_SCENARIOS[0]!;
  }
  if (/churn|risk|next quarter|forecast|predict/.test(text)) {
    return byId('refused') ?? MOCK_SCENARIOS[0]!;
  }
  if (/roraima|\brr\b/.test(text)) return byId('insufficient') ?? MOCK_SCENARIOS[0]!;
  if (/by state/.test(text)) return byId('error') ?? MOCK_SCENARIOS[0]!;
  if (/unusual|anomal|spike|normal range/.test(text)) {
    return byId('anomaly') ?? MOCK_SCENARIOS[0]!;
  }
  if (/\bq[1-4]\b|driving|driver|contribut|why did/.test(text)) {
    // "Why did revenue drop in August?" has no period, so it clarifies; the
    // same question with a quarter resolves to driver attribution.
    if (/\bq[1-4]\b|\b20\d\d\b/.test(text)) return byId('driver') ?? MOCK_SCENARIOS[0]!;
    return byId('clarify') ?? MOCK_SCENARIOS[0]!;
  }
  if (/how many|count|total/.test(text)) return byId('lookup') ?? MOCK_SCENARIOS[0]!;
  return byId('clarify') ?? MOCK_SCENARIOS[0]!;
}
