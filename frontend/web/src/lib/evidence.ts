/**
 * Narrowing `EvidenceBlock.output`, which is `Any` in the Pydantic contract and
 * therefore carries no guarantee at all. Everything here validates the shape
 * before trusting it, and returns null rather than throwing.
 */

import type {
  AnalystOutput,
  AnomalyResult,
  DriverResult,
  EvidenceBlock,
  LookupOutput,
  Range,
} from '@/types/envelope';

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function isRange(value: unknown): value is Range {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    typeof value[0] === 'number' &&
    typeof value[1] === 'number'
  );
}

export function asLookup(block: EvidenceBlock): LookupOutput | null {
  if (block.module !== 'lookup') return null;
  const output: unknown = block.output;
  if (!isObject(output)) return null;
  const columns = output['columns'];
  if (!Array.isArray(columns) || !Array.isArray(output['rows'])) return null;
  // A V2 lookup block names its columns as bare strings and carries no
  // row_count; it is reshaped here (never re-counted) so every reader sees one
  // contract.
  if (columns.every((column) => typeof column === 'string')) {
    return {
      query_id: String(output['query_id'] ?? ''),
      columns: (columns as string[]).map((name) => ({ name, type: '' })),
      rows: output['rows'] as LookupOutput['rows'],
      row_count: typeof output['row_count'] === 'number' ? output['row_count'] : null,
      truncated: output['truncated'] === true,
    };
  }
  return output as unknown as LookupOutput;
}

export function asAnalystOutput(block: EvidenceBlock): AnalystOutput | null {
  if (block.module === 'lookup') return null;
  const output: unknown = block.output;
  if (!isObject(output)) return null;
  if (typeof output['module'] !== 'string' || typeof output['status'] !== 'string') {
    return null;
  }
  return output as unknown as AnalystOutput;
}

export function asAnomalyResult(block: EvidenceBlock): AnomalyResult | null {
  const output = asAnalystOutput(block);
  if (!output || output.module !== 'anomaly') return null;
  const result: unknown = output.result;
  if (!isObject(result)) return null;
  if (
    typeof result['actual'] !== 'number' ||
    typeof result['expected'] !== 'number' ||
    !isRange(result['expected_range'])
  ) {
    return null;
  }
  return result as unknown as AnomalyResult;
}

export function asDriverResult(block: EvidenceBlock): DriverResult | null {
  const output = asAnalystOutput(block);
  if (!output || output.module !== 'driver') return null;
  const result: unknown = output.result;
  if (!isObject(result)) return null;
  if (typeof result['total_change'] !== 'number' || !Array.isArray(result['drivers'])) {
    return null;
  }
  return result as unknown as DriverResult;
}

/* ---------- deriving a time series for the anomaly chart ---------- */

export interface SeriesPoint {
  label: string;
  value: number;
}

/**
 * `AnomalyResult` carries a single period — no series. So we look for a sibling
 * `lookup` block whose columns pair something time-like with a measure, and
 * chart that. When nothing qualifies, the caller falls back to the horizontal
 * range bar (never a one-point line chart).
 */
export function deriveSeries(blocks: readonly EvidenceBlock[]): readonly SeriesPoint[] {
  for (const block of blocks) {
    const lookup = asLookup(block);
    if (!lookup || lookup.rows.length < 3) continue;

    const names = lookup.columns.map((column) => column.name.toLowerCase());
    const types = lookup.columns.map((column) => column.type.toLowerCase());

    const timeIndex = names.findIndex(
      (name, index) =>
        /date|time|month|week|day|quarter|year|period/.test(name) ||
        /date|time/.test(types[index] ?? ''),
    );
    if (timeIndex === -1) continue;

    /**
     * Declared types are not dependable: the governed compiler reports its
     * measures as the bare type "number", which no SQL type name matches. So
     * the declared type is only a hint, and the real test is whether the column
     * actually holds numbers.
     */
    const holdsNumbers = (index: number) =>
      lookup.rows.some((row) => typeof row[index] === 'number');

    const measureIndex = names.findIndex(
      (_, index) =>
        index !== timeIndex &&
        (/int|real|float|numeric|number|decimal|double|money/.test(types[index] ?? '') ||
          holdsNumbers(index)),
    );
    if (measureIndex === -1) continue;

    const points: SeriesPoint[] = [];
    for (const row of lookup.rows) {
      const rawLabel = row[timeIndex];
      const rawValue = row[measureIndex];
      if (typeof rawValue !== 'number') continue;
      points.push({ label: String(rawLabel ?? ''), value: rawValue });
    }
    if (points.length >= 3) return points;
  }
  return [];
}

/** Drivers sorted by absolute contribution, largest first. */
export function sortDrivers(result: DriverResult): DriverResult['drivers'] {
  return [...result.drivers].sort(
    (a, b) => Math.abs(b.contribution) - Math.abs(a.contribution),
  );
}
