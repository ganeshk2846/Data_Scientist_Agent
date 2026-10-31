/**
 * Resolving a `VisualizationSpec` to the rows it draws (contracts.md §7).
 *
 * A spec carries no data (VZ-1); it names a step and columns. This module
 * finds those rows in the envelope the backend already sent and reads cells
 * out of them. SAFE-8: it never sorts, slices, bins, totals or rounds — the
 * top-N cut, if any, was applied by the backend (VZ-3) and is in the caption.
 *
 * Two references, as `backend/src/viz/builder.py` documents them:
 *   - `source_query_id`    → the `lookup` evidence block with that query id
 *   - `source_artifact_id` → `"<step_id>:<tool>#<path>"`: the step's engine
 *     evidence block, then a dotted path into its output (`result.points`)
 */

import { asLookup } from './evidence';
import type { AnswerEnvelope, EvidenceBlock } from '@/types/envelope';
import type { AnswerEnvelopeV2, VisualizationSpec } from '@/types/v2';

export type Record_ = Readonly<Record<string, unknown>>;

export interface ResolvedViz {
  /** One object per row, keyed by the column names the spec uses. */
  records: readonly Record_[];
  /** The column names, in source order, for the "view as table". */
  columns: readonly string[];
}

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/** `a.b.0` against nested objects and arrays; undefined when absent. */
export function readPath(node: unknown, path: string): unknown {
  let current: unknown = node;
  for (const part of path.split('.')) {
    if (Array.isArray(current)) {
      const index = Number(part);
      if (!Number.isInteger(index)) return undefined;
      current = current[index];
    } else if (isObject(current)) {
      current = current[part];
    } else {
      return undefined;
    }
  }
  return current;
}

function engineBlock(envelope: AnswerEnvelopeV2, stepId: string, tool: string): EvidenceBlock | null {
  const module = tool.replace(/^python\./, '');
  const summary = envelope.step_results.find((step) => step.step_id === stepId);
  const candidates = envelope.evidence.filter((block) => block.module === module);
  if (summary) {
    // The composer stamps a step's claim ids on its evidence block, so an
    // exact match identifies the block even when one engine ran twice.
    const exact = candidates.find(
      (block) =>
        block.source_claims.length === summary.claim_ids.length &&
        block.source_claims.every((id, index) => id === summary.claim_ids[index]),
    );
    if (exact) return exact;
  }
  // Otherwise the n-th step with this tool owns the n-th block of the module.
  const order = envelope.step_results.filter((step) => step.tool === tool && step.status === 'ok');
  const position = order.findIndex((step) => step.step_id === stepId);
  return position >= 0 ? (candidates[position] ?? null) : null;
}

export function resolveViz(envelope: AnswerEnvelope, spec: VisualizationSpec): ResolvedViz | null {
  const v2 = envelope as unknown as AnswerEnvelopeV2;

  if (spec.source_query_id) {
    for (const block of envelope.evidence) {
      const lookup = asLookup(block);
      if (!lookup || lookup.query_id !== spec.source_query_id) continue;
      const columns = lookup.columns.map((column) => column.name);
      const records = lookup.rows.map((row) =>
        Object.fromEntries(columns.map((name, index) => [name, row[index]])),
      );
      return { records, columns };
    }
    return null;
  }

  if (spec.source_artifact_id) {
    const [artifact, path] = spec.source_artifact_id.split('#');
    if (!artifact || !path) return null;
    const split = artifact.indexOf(':');
    if (split < 0) return null;
    const block = engineBlock(v2, artifact.slice(0, split), artifact.slice(split + 1));
    if (!block) return null;
    const node = readPath(block.output, path);
    const items = Array.isArray(node) ? node : isObject(node) ? [node] : [];
    const records = items.filter(isObject) as Record_[];
    if (records.length === 0) return null;
    return { records, columns: Object.keys(records[0] ?? {}) };
  }
  return null;
}

/** The columns a spec actually draws, for a focused "view as table". */
export function specColumns(spec: VisualizationSpec): readonly string[] {
  const { x, y, series, band } = spec.encoding;
  const names = [x.column, ...(series ? [series.column] : []), y.column];
  if (band) names.push(band.lower_column, band.upper_column);
  return names.filter((name, index) => names.indexOf(name) === index);
}

/** A cell as a number when it holds one, else null. Never coerces strings. */
export function numberAt(record: Record_, column: string): number | null {
  const value = readPath(record, column);
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function textAt(record: Record_, column: string): string {
  const value = readPath(record, column);
  return value === null || value === undefined ? '' : String(value);
}
