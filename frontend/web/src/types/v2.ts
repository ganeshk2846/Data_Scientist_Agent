/**
 * A mirror of the V2 additions in `backend/src/contracts/v2.py` (§1-8 of
 * `spec/v2/contracts.md`), limited to what the interface reads.
 *
 * `AnswerEnvelopeV2` extends the V1 envelope, so a V1 envelope
 * (`contract_version: "1.0.0"`) keeps rendering exactly as before: every V2
 * surface checks `asV2()` first and renders nothing when it is absent.
 */

import type { ActionOption, AnswerEnvelope, RunStatus } from './envelope';

export type IntentName =
  | 'discovery'
  | 'clarify'
  | 'descriptive'
  | 'diagnostic'
  | 'impact'
  | 'forecast'
  | 'scenario'
  | 'prescriptive';

export type ToolName =
  | 'sql'
  | 'catalog'
  | 'analytical_table'
  | 'python.anomaly'
  | 'python.driver'
  | 'python.forecast'
  | 'python.impact'
  | 'python.scenario'
  | 'python.segment';

export type ToolStatus = 'ok' | 'empty' | 'insufficient_evidence' | 'refused' | 'skipped' | 'error';

/* ---------- §2 ResolvedQuestion (the fields the UI reads) ---------- */

export interface ResolvedQuestion {
  text: string;
  effective_text: string | null;
  metric_id: string | null;
  inherited_fields: readonly string[];
  resolution_source: string;
  assumptions: readonly string[];
}

/* ---------- §3 IntentResult (the fields the UI reads) ---------- */

export interface ScoredIntent {
  intent: IntentName;
  score: number;
  span: string;
}

export interface IntentResult {
  intents: readonly ScoredIntent[];
  confidence: number;
  reason: string;
}

/* ---------- §4 ClarificationRequest ---------- */

export interface ClarificationOption {
  option_id: string;
  label: string;
  detail: string | null;
  resolves_to: Record<string, unknown>;
  recommended: boolean;
}

export interface ClarificationRequest {
  contract_version: string;
  what_understood: string;
  what_needs_clarification: string;
  question: string;
  options: readonly ClarificationOption[];
  default_assumption: { option_id: string; rationale: string };
  round: 1 | 2;
  slot: string;
  of_run_id: string | null;
}

/* ---------- §5 Plan ---------- */

export interface PlanStep {
  step_id: string;
  tool: ToolName;
  params: Record<string, unknown>;
  depends_on: readonly string[];
  produces: string;
  optional: boolean;
  purpose: string;
}

export interface Plan {
  plan_id: string;
  steps: readonly PlanStep[];
  intents_covered: readonly IntentName[];
  intents_dropped: readonly { intent: IntentName; reason: string }[];
}

/* ---------- §7 VisualizationSpec ---------- */

export type VizKind =
  | 'line'
  | 'bar'
  | 'grouped_bar'
  | 'waterfall'
  | 'range_band'
  | 'forecast_fan'
  | 'scatter'
  | 'table';

export interface VizAxis {
  column: string;
  role: 'time' | 'dimension' | 'measure';
  label: string;
  unit: string | null;
  zero_baseline: boolean | null;
}

export interface VizEncoding {
  x: VizAxis;
  y: VizAxis;
  series: { column: string; label: string } | null;
  band: { lower_column: string; upper_column: string; label: string } | null;
  sort: { column: string; direction: 'asc' | 'desc' } | null;
  limit: number | null;
}

export interface VizAnnotation {
  kind: 'point' | 'band' | 'line' | 'label';
  at: { x: string | null; x_start: string | null; x_end: string | null; y: number | null };
  label: string;
  /** Semantic, never a colour (VZ-4): the frontend maps it onto its tokens. */
  emphasis: 'normal' | 'attention';
  claim_id: string | null;
}

export interface VisualizationSpec {
  contract_version: string;
  viz_id: string;
  kind: VizKind;
  title: string;
  source_step_id: string;
  source_query_id: string | null;
  source_artifact_id: string | null;
  encoding: VizEncoding;
  annotations: readonly VizAnnotation[];
  caption: string;
  claim_ids: readonly string[];
}

/* ---------- §8 envelope additions ---------- */

export interface StepResultSummary {
  step_id: string;
  tool: ToolName;
  status: ToolStatus;
  purpose: string;
  summary: string;
  claim_ids: readonly string[];
  duration_ms: number;
  reason: string | null;
}

export interface FollowUpSuggestion {
  text: string;
  intent: IntentName;
  rationale: string;
  answerable: true;
}

export interface AnswerEnvelopeV2 extends Omit<AnswerEnvelope, 'clarification'> {
  contract_version: '2.0.0';
  resolved_question: ResolvedQuestion | null;
  intent: IntentResult | null;
  plan: Plan | null;
  step_results: readonly StepResultSummary[];
  visualizations: readonly VisualizationSpec[];
  assumptions: readonly string[];
  follow_ups: readonly FollowUpSuggestion[];
  clarification: ClarificationRequest | null;
  next_actions: readonly ActionOption[];
}

/* ---------- V2 SSE events (backend/src/pipeline_v2.py, executor_v2.py) ---------- */

interface V2EventBase {
  seq: number;
  run_id: string;
}

export interface ContextEvent extends V2EventBase {
  type: 'context';
  mode: 'followup' | 'clarify' | 'reset' | 'cold';
  shape: string | null;
  interpreted_as: string | null;
  inherited_fields: readonly string[];
  prior_turn_id: string | null;
}

export interface IntentEvent extends V2EventBase {
  type: 'intent';
  intents: readonly ScoredIntent[];
  confidence: number;
  reason: string;
}

export interface GroundingEvent extends V2EventBase {
  type: 'grounding';
  status: 'grounded' | 'clarify';
  metric_id: string | null;
  assumptions: readonly string[];
}

export interface PlanEvent extends V2EventBase {
  type: 'plan';
  plan_id: string;
  attempt: number;
  steps: readonly {
    step_id: string;
    tool: ToolName;
    depends_on: readonly string[];
    purpose: string;
    optional: boolean;
  }[];
}

export interface PlanStepStartedEvent extends V2EventBase {
  type: 'plan_step_started';
  step_id: string;
  tool: ToolName;
  purpose: string;
}

export interface PlanStepFinishedEvent extends V2EventBase {
  type: 'plan_step_finished';
  step_id: string;
  tool: ToolName;
  status: ToolStatus;
  duration_ms: number;
  summary: string;
}

export interface EngineRunningEvent extends V2EventBase {
  type: 'engine_running';
  step_id: string;
  tool: ToolName;
  summary: string;
}

export interface ComposeEvent extends V2EventBase {
  type: 'compose';
  status: RunStatus;
  claims: number;
}

export interface ReplanEvent extends V2EventBase {
  type: 'replan';
  attempt: number;
}

export type V2RunEvent =
  | ContextEvent
  | IntentEvent
  | GroundingEvent
  | PlanEvent
  | PlanStepStartedEvent
  | PlanStepFinishedEvent
  | EngineRunningEvent
  | ComposeEvent
  | ReplanEvent;

export const V2_EVENT_TYPES: readonly V2RunEvent['type'][] = [
  'context',
  'intent',
  'grounding',
  'plan',
  'plan_step_started',
  'plan_step_finished',
  'engine_running',
  'compose',
  'replan',
];

/**
 * The V2 `clarify` event carries the options too. Its V1 fields are kept, so
 * a V1 consumer reading only those two strings is unaffected.
 */
export interface ClarifyEventV2Fields {
  question?: string;
  slot?: string;
  round?: 1 | 2;
  options?: readonly { option_id: string; label: string; detail: string | null }[];
  default_option_id?: string;
}

/* ---------- feedback (backend/src/feedback.py) ---------- */

export type FeedbackRating = 'up' | 'down';

export interface FeedbackRecord {
  session_id: string;
  run_id: string;
  rating: FeedbackRating;
  reason: string | null;
  created_at: string;
}
