/**
 * Reading the V2 envelope. Pure, React-free, and SAFE-8: every helper here
 * *locates* something the envelope states — it never derives a figure.
 */

import type { AnswerEnvelope, LedgerClaim } from '@/types/envelope';
import type {
  AnswerEnvelopeV2,
  IntentName,
  ToolName,
  VisualizationSpec,
} from '@/types/v2';

/** The V2 view of an envelope, or null for a V1 one (which renders as before). */
export function asV2(envelope: AnswerEnvelope | null | undefined): AnswerEnvelopeV2 | null {
  if (!envelope || envelope.contract_version !== '2.0.0') return null;
  const candidate = envelope as unknown as Partial<AnswerEnvelopeV2>;
  if (!Array.isArray(candidate.step_results) || !Array.isArray(candidate.visualizations)) {
    return null;
  }
  return envelope as unknown as AnswerEnvelopeV2;
}

export type AnswerLayout = 'why' | 'forecast' | 'whatif' | 'nowwhat' | 'discovery' | 'impact' | 'what';

/**
 * Which answer layout an envelope gets, read from the backend's own intent
 * classification. Several intents can be present (a compound question); the
 * most decision-shaped one wins, so "why ... and what should we do" leads with
 * the ranked actions and still shows the drivers beneath.
 */
export function layoutsFor(envelope: AnswerEnvelopeV2): readonly AnswerLayout[] {
  const names = new Set<IntentName>(envelope.intent?.intents.map((item) => item.intent) ?? []);
  const layouts: AnswerLayout[] = [];
  if (names.has('prescriptive')) layouts.push('nowwhat');
  if (names.has('diagnostic')) layouts.push('why');
  if (names.has('impact')) layouts.push('impact');
  if (names.has('scenario')) layouts.push('whatif');
  if (names.has('forecast')) layouts.push('forecast');
  if (names.has('discovery')) layouts.push('discovery');
  if (layouts.length === 0) layouts.push('what');
  return layouts;
}

export const LAYOUT_LABEL: Record<AnswerLayout, string> = {
  why: 'Why',
  forecast: 'Forecast',
  whatif: 'What if',
  nowwhat: 'Now what',
  discovery: 'Discovery',
  impact: 'So what',
  what: 'What',
};

/* ---------- plan steps ---------- */

/** The type badge on a plan step: what kind of work produced its figures. */
export function stepBadge(tool: ToolName): string {
  switch (tool) {
    case 'sql':
      return 'SQL';
    case 'catalog':
      return 'Catalog';
    case 'analytical_table':
      return 'Analytical table';
    case 'python.forecast':
      return 'Python · forecast';
    case 'python.driver':
    case 'python.anomaly':
      return 'Python · diagnostic';
    case 'python.impact':
      return 'Python · impact';
    case 'python.scenario':
      return 'Python · scenario';
    case 'python.segment':
      return 'Python · segment';
  }
}

export function isLiveModel(tool: ToolName): boolean {
  return tool.startsWith('python.');
}

/**
 * How long a live model usually takes, in seconds, for the "this can take ~N s"
 * notice. This is interface copy, not a measurement: it never appears beside a
 * data figure, and the step's real duration replaces it once the step ends.
 */
export const TYPICAL_MODEL_SECONDS: Partial<Record<ToolName, number>> = {
  'python.forecast': 10,
  'python.driver': 6,
  'python.anomaly': 3,
  'python.impact': 3,
  'python.scenario': 6,
  'python.segment': 6,
};

/* ---------- forecast fit quality ---------- */

/** A ledger claim whose text names the term, located verbatim (never computed). */
export function findClaim(claims: readonly LedgerClaim[], pattern: RegExp): LedgerClaim | null {
  return claims.find((claim) => pattern.test(claim.text)) ?? null;
}

/* ---------- visualizations ---------- */

/** Trend / seasonality decompositions are shown on request, not by default. */
export function isComponentSpec(spec: VisualizationSpec): boolean {
  return /^(Trend|Seasonality) component$/.test(spec.title);
}

/* ---------- discovery ---------- */

/**
 * The example questions the catalog answer states, quoted as “Try: …”. They
 * are the backend's own sentences, lifted out so they can be clicked.
 */
export function exampleQuestions(text: string | null): readonly string[] {
  if (!text) return [];
  const found: string[] = [];
  const pattern = /Try:\s*[“"]([^”"]+)[”"]/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    const question = match[1]?.trim();
    if (question && !found.includes(question)) found.push(question);
  }
  return found.slice(0, 8);
}

/** True when any step read a synthetic table (V2-SYN-4). */
export function readsSynthetic(envelope: AnswerEnvelope): boolean {
  return envelope.caveats.some((caveat) => /synthetic/i.test(caveat));
}

/* ---------- the plan, settled ---------- */

import type { PlanStepProgress } from './runState';

/** The plan checklist for a settled answer, from `plan` + `step_results`. */
export function planFromEnvelope(envelope: AnswerEnvelopeV2): readonly PlanStepProgress[] {
  if (!envelope.plan) return [];
  return envelope.plan.steps.map((step) => {
    const result = envelope.step_results.find((item) => item.step_id === step.step_id);
    return {
      stepId: step.step_id,
      tool: step.tool,
      purpose: step.purpose,
      dependsOn: step.depends_on,
      state: result?.status ?? 'skipped',
      modelRunning: false,
      durationMs: result?.duration_ms ?? null,
      summary: result ? (result.reason ?? result.summary) : null,
    };
  });
}
