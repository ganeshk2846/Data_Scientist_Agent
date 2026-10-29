/**
 * Linking the narrative to the evidence ledger.
 *
 * The backend does not annotate the conclusion — it only guarantees that every
 * number in it was approved by some claim. So we locate each claim's number
 * tokens inside the conclusion text and attach the claim there.
 *
 * Real ledgers carry noisy tokens: a single query claim can list both "6,512"
 * and "1" (the row count). Matching therefore goes longest-token-first, only on
 * whole-number boundaries, and never into a span already claimed — otherwise
 * the "1" would land inside "6,512".
 */

import type { LedgerClaim } from '@/types/envelope';

export interface NarrativeText {
  kind: 'text';
  text: string;
}

export interface NarrativeNumber {
  kind: 'number';
  text: string;
  /** Claims whose ledger entry approved this exact token. */
  claims: readonly LedgerClaim[];
}

export type NarrativeSegment = NarrativeText | NarrativeNumber;

interface Match {
  start: number;
  end: number;
  token: string;
  claims: LedgerClaim[];
}

/** A number token may be shared by several claims; index them together. */
function indexTokens(claims: readonly LedgerClaim[]): Map<string, LedgerClaim[]> {
  const index = new Map<string, LedgerClaim[]>();
  for (const claim of claims) {
    for (const number of claim.numbers) {
      const token = number.token.trim();
      if (!token) continue;
      const bucket = index.get(token);
      if (bucket) bucket.push(claim);
      else index.set(token, [claim]);
    }
  }
  return index;
}

const DIGIT = /[0-9]/;

/**
 * True when the token does not continue past `index` into a longer number.
 *
 * A `.` or `,` only continues a number when a digit follows it, so the full
 * stop in "…is 6,512." is a boundary while the comma in "6,512" is not. A
 * trailing `%` always belongs to the number, so "12.4" must not match inside
 * "12.4%".
 */
function isBoundary(text: string, index: number, side: 'left' | 'right'): boolean {
  if (index < 0 || index >= text.length) return true;
  const char = text[index] ?? '';
  if (DIGIT.test(char)) return false;
  if (side === 'right' && char === '%') return false;
  if (char === '.' || char === ',') {
    const beyond = side === 'right' ? text[index + 1] : text[index - 1];
    return !DIGIT.test(beyond ?? '');
  }
  return true;
}

/**
 * Splits the conclusion into plain text and number segments, each number
 * carrying the claims that approved it.
 */
export function annotateNarrative(
  conclusion: string,
  claims: readonly LedgerClaim[],
): readonly NarrativeSegment[] {
  if (!conclusion) return [];
  const index = indexTokens(claims);
  if (index.size === 0) return [{ kind: 'text', text: conclusion }];

  // Longest first, so "6,512" wins before "1" can match inside it.
  const tokens = [...index.keys()].sort((a, b) => b.length - a.length);
  const matches: Match[] = [];
  const taken: boolean[] = new Array(conclusion.length).fill(false);

  for (const token of tokens) {
    let from = 0;
    for (;;) {
      const at = conclusion.indexOf(token, from);
      if (at === -1) break;
      const end = at + token.length;
      from = at + 1;

      if (
        !isBoundary(conclusion, at - 1, 'left') ||
        !isBoundary(conclusion, end, 'right')
      ) {
        continue;
      }
      let overlaps = false;
      for (let i = at; i < end; i += 1) {
        if (taken[i]) {
          overlaps = true;
          break;
        }
      }
      if (overlaps) continue;

      for (let i = at; i < end; i += 1) taken[i] = true;
      matches.push({ start: at, end, token, claims: index.get(token) ?? [] });
    }
  }

  if (matches.length === 0) return [{ kind: 'text', text: conclusion }];
  matches.sort((a, b) => a.start - b.start);

  const segments: NarrativeSegment[] = [];
  let cursor = 0;
  for (const match of matches) {
    if (match.start > cursor) {
      segments.push({ kind: 'text', text: conclusion.slice(cursor, match.start) });
    }
    segments.push({ kind: 'number', text: match.token, claims: match.claims });
    cursor = match.end;
  }
  if (cursor < conclusion.length) {
    segments.push({ kind: 'text', text: conclusion.slice(cursor) });
  }
  return segments;
}

/** Claims that never matched the narrative, so they can still be listed. */
export function unplacedClaims(
  segments: readonly NarrativeSegment[],
  claims: readonly LedgerClaim[],
): readonly LedgerClaim[] {
  const placed = new Set<string>();
  for (const segment of segments) {
    if (segment.kind !== 'number') continue;
    for (const claim of segment.claims) placed.add(claim.claim_id);
  }
  return claims.filter((claim) => !placed.has(claim.claim_id));
}

export const CLAIM_KIND_LABEL: Record<LedgerClaim['kind'], string> = {
  fact: 'Fact',
  concentration: 'Concentration',
  co_movement: 'Co-movement',
  comparison: 'Comparison',
  consistent_with: 'Consistent with',
  hypothesis: 'Hypothesis',
};

/** Grade 4 is the only grade the fact checker lets carry causal wording. */
export const GRADE_LABEL: Record<number, string> = {
  0: 'ungraded',
  1: 'direct query evidence',
  2: 'corroborated',
  3: 'strong association',
  4: 'causal-strength evidence',
};
