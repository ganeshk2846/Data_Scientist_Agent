/**
 * Meaningful titles for evidence cards.
 *
 * "Query result" tells the reader nothing. A title like "Revenue · August 2018"
 * tells them what they are looking at — and every part of it comes from the
 * envelope's own `scope`, never from inspecting or interpreting the numbers.
 */

import { formatWindow, humanise } from './format';
import type { AnswerEnvelope, EvidenceBlock, LookupOutput } from '@/types/envelope';

/** A single-cell result worth setting as a hero figure. */
export interface HeroFigure {
  value: number;
  /** The column name, as the unit line beneath the figure. */
  unit: string;
  /** The declared column type, for the mono caption. */
  type: string;
}

/**
 * A lookup that returned exactly one row and one column is a headline number,
 * not a table. Anything else stays a table.
 */
export function asHeroFigure(output: LookupOutput): HeroFigure | null {
  if ((output.row_count !== null && output.row_count !== 1) || output.rows.length !== 1) return null;
  if (output.columns.length !== 1) return null;
  const column = output.columns[0];
  const cell = output.rows[0]?.[0];
  if (!column || typeof cell !== 'number') return null;
  return { value: cell, unit: column.name, type: column.type };
}

/**
 * The scope's metric and window, as a title. Falls back through what the
 * envelope actually has rather than inventing a label.
 */
export function evidenceTitle(
  envelope: AnswerEnvelope,
  block: EvidenceBlock,
  output: LookupOutput | null,
): { title: string; period: string | null } {
  const period = formatWindow(envelope.scope.window);

  if (block.module === 'anomaly') {
    return { title: 'Anomaly detection', period };
  }
  if (block.module === 'driver') {
    return { title: 'Driver attribution', period };
  }
  if (block.module === 'risk') {
    return { title: 'Risk assessment', period };
  }

  // A lookup: prefer the governed metric name, then the single column name.
  const metric = envelope.scope.metric;
  if (metric) return { title: humanise(metric), period };
  if (output?.columns.length === 1 && output.columns[0]) {
    return { title: humanise(output.columns[0].name), period };
  }
  if (output && output.columns.length > 1) {
    return { title: 'Result set', period };
  }
  return { title: 'Query result', period };
}

/**
 * Comparative runs produce two lookups over different windows, but `scope`
 * only carries the current one — so a second identical title would be a lie.
 * Disambiguate by position instead, which is the only thing we actually know.
 */
export function disambiguateTitles(
  titles: readonly { title: string; period: string | null }[],
): readonly { title: string; period: string | null }[] {
  const counts = new Map<string, number>();
  for (const entry of titles) counts.set(entry.title, (counts.get(entry.title) ?? 0) + 1);

  const seen = new Map<string, number>();
  return titles.map((entry) => {
    if ((counts.get(entry.title) ?? 0) < 2) return entry;
    const index = (seen.get(entry.title) ?? 0) + 1;
    seen.set(entry.title, index);
    // The period is dropped: we cannot attribute scope.window to both.
    return { title: `${entry.title} · series ${index}`, period: null };
  });
}
