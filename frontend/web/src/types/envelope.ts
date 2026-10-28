/**
 * A 1:1 mirror of `backend/src/contracts/models.py`, limited to the
 * `AnswerEnvelope` subtree plus the ask/response pair.
 *
 * Pydantic `tuple[X, ...]` becomes `readonly X[]`; `X | None = None` becomes
 * `X | null` (the backend always serialises the key, so these are present-and-
 * null rather than optional). Keep this file in lockstep with the Python
 * contract — it is frozen there and strict about unknown fields.
 */

/* ---------- shared literal unions ---------- */

export type RunStatus =
  | 'answered'
  | 'clarify'
  | 'refused'
  | 'blocked'
  | 'insufficient_evidence'
  | 'error';

export type RouteLabel =
  | 'lookup'
  | 'anomaly'
  | 'driver'
  | 'risk'
  | 'clarify'
  | 'refused'
  | 'blocked';

export type GuardReason = 'write_attempt' | 'injection' | 'unsafe';
export type SqlOrigin = 'compiler' | 'generator' | 'repair';
export type ValidationMode = 'benchmark' | 'enterprise';
export type MetricTimeGrain = 'day' | 'week' | 'month' | 'quarter' | 'year';

export type ClaimKind =
  | 'fact'
  | 'concentration'
  | 'co_movement'
  | 'comparison'
  | 'consistent_with'
  | 'hypothesis';

export type AnalystModule = 'anomaly' | 'driver' | 'risk';
export type EvidenceModule = 'lookup' | AnalystModule;
export type AnalystStatus = 'ok' | 'insufficient_evidence';

export type AnomalyVerdict = 'unusual' | 'within_normal_range' | 'insufficient_evidence';
export type AnomalyPersistence = 'one_off' | 'sustained' | 'drift' | 'unknown';
export type AnomalyBaselineKind = 'seasonal' | 'robust_trailing';

export type AnalystColumnRole = 'dimension' | 'measure' | 'time' | 'key' | 'label';

/** A closed numeric interval, serialised by Pydantic as a 2-tuple. */
export type Range = readonly [number, number];

/* ---------- request / response ---------- */

export interface AskRequest {
  question: string;
  session_id: string;
  clarification_of?: string | null;
}

export interface AskResponse {
  contract_version: string;
  run_id: string;
}

/** The HTTP 202 body of `GET /api/runs/{id}` - not an envelope. */
export interface RunPending {
  contract_version: string;
  run_id: string;
  status: 'running';
}

/* ---------- evidence ledger ---------- */

export interface ClaimNumber {
  token: string;
  value: number;
  unit: string | null;
}

export interface ClaimSource {
  type: 'query' | 'artifact';
  id: string;
}

export interface LedgerClaim {
  claim_id: string;
  text: string;
  numbers: readonly ClaimNumber[];
  source: ClaimSource;
  /** 0-4. Grade 4 is the only grade allowed to carry causal wording. */
  grade: number;
  kind: ClaimKind;
}

/* ---------- analyst results ---------- */

export interface AnomalyResult {
  verdict: AnomalyVerdict;
  window: string;
  actual: number;
  expected: number;
  expected_range: Range;
  deviation_pct: number;
  robust_score: number;
  persistence: AnomalyPersistence;
  threshold: number;
  correction_used: string | null;
  calendar_effects: readonly string[];
  baseline_kind: AnomalyBaselineKind;
}

export interface DriverContribution {
  dimension: string;
  value: string;
  contribution: number;
  share: number;
  interval: Range;
  sample_size: number;
  unstable: boolean;
  /** 0-4 evidence grade. */
  grade: number;
  data_needed_to_strengthen: readonly string[];
}

export interface DriverResult {
  metric: string;
  current_period: string;
  comparison_period: string;
  total_change: number;
  drivers: readonly DriverContribution[];
  reconciliation_error: number;
  candidates_examined: number;
  correction_used: string | null;
}

export interface AnalystArtifact {
  artifact_id: string;
  kind: 'chart_data' | 'table' | 'model_card';
  uri: string;
}

/**
 * What `EvidenceBlock.output` actually holds for an analyst module: the full
 * `AnalystOutput.model_dump()`, so the result sits at `.result`.
 */
export interface AnalystOutput {
  module: AnalystModule;
  status: AnalystStatus;
  reason: string | null;
  result: AnomalyResult | DriverResult | null;
  parameters: Record<string, unknown>;
  assumptions: readonly string[];
  sources: readonly string[];
  artifacts: readonly AnalystArtifact[];
}

/* ---------- evidence blocks ---------- */

export interface LookupColumn {
  name: string;
  type: string;
}

/**
 * The `lookup` payload is an ad-hoc dict built in `service.py:_evidence`, with
 * no Pydantic model behind it. Treat it as unvalidated.
 */
export interface LookupOutput {
  query_id: string;
  columns: readonly LookupColumn[];
  rows: readonly (readonly unknown[])[];
  row_count: number;
  truncated: boolean;
}

/**
 * `EvidenceBlock.output` is typed `Any` in the contract, so this discriminated
 * union is our own narrowing, not a backend guarantee. Validate defensively.
 */
export type EvidenceBlock =
  | { module: 'lookup'; output: LookupOutput; source_claims: readonly string[] }
  | { module: AnalystModule; output: AnalystOutput; source_claims: readonly string[] };

/* ---------- envelope sections ---------- */

export interface EnvelopeScope {
  metric: string | null;
  window: string | null;
  filters: readonly string[];
  grain: string | null;
  /** Never populated by the current backend path. */
  data_range: string | null;
  governed: boolean;
}

export interface EnvelopeQueryRecord {
  query_id: string;
  sql: string;
  status: 'ok' | 'rejected' | 'error';
  duration_ms: number;
  rows_scanned: number | null;
  /** Never populated by the current backend path. */
  est_cost: number | null;
  /** Stamped per run, not per query - shown once at run level. */
  origin: SqlOrigin;
  /** Never populated by the current backend path. */
  repair_of: string | null;
  validation_mode: ValidationMode | null;
}

export interface ActionOption {
  action_id: string;
  title: string;
  rank: number;
  assumptions: readonly string[];
  trade_offs: readonly string[];
  sensitivity: string;
  monitor: readonly string[];
  data_that_would_change_ranking: readonly string[];
  kind: 'intervention' | 'information_gathering';
}

export interface MethodStep {
  name: string;
  params: Record<string, unknown>;
}

export interface RouteSummary {
  labels: readonly string[];
  /** Effectively 0.70-1.00: the RouterResult validator rejects less. */
  confidence: number;
  reason: string;
}

export interface RefusalBlock {
  missing: readonly string[];
  /** Never populated by the current backend path. */
  closest_answerable: string | null;
}

export interface BlockBlock {
  reason: GuardReason;
  detail: string;
}

export interface ClarificationResult {
  what_understood: string;
  what_needs_clarification: string;
}

export interface RunMetrics {
  latency_ms: number;
  tokens: number;
  queries: number;
  rows: number;
  retries: number;
}

export interface Provenance {
  model_name: string;
  model_version: string;
  commit: string;
  snapshot_id: string;
  catalog_version: string;
  timestamp: string;
}

/* ---------- the envelope ---------- */

export interface AnswerEnvelope {
  contract_version: string;
  run_id: string;
  status: RunStatus;
  route: RouteSummary;
  conclusion: string | null;
  scope: EnvelopeScope;
  evidence: readonly EvidenceBlock[];
  claims: readonly LedgerClaim[];
  method: readonly MethodStep[];
  queries: readonly EnvelopeQueryRecord[];
  caveats: readonly string[];
  causal_boundary_note: string | null;
  /** Always `[]` from the live backend; populated only in mock mode. */
  next_actions: readonly ActionOption[];
  clarification: ClarificationResult | null;
  refusal: RefusalBlock | null;
  block: BlockBlock | null;
  run_metrics: RunMetrics;
  provenance: Provenance;
}
