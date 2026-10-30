/**
 * Answer feedback, remembered in this browser (and, live, also sent to
 * `POST /api/sessions/{id}/feedback`). One rating per run; rating again
 * replaces it. Ratings never touch an answer: nothing reads them back into a
 * figure, a ranking or a route.
 */

import { KEYS, isRecord, readJson, writeJson } from './storage';
import type { FeedbackRating } from '@/types/v2';

export interface LocalFeedback {
  runId: string;
  rating: FeedbackRating;
  reason: string | null;
  at: number;
}

export const MAX_REASON = 500;
const MAX_STORED = 200;

export function loadFeedback(): readonly LocalFeedback[] {
  return (
    readJson<readonly LocalFeedback[]>(KEYS.feedback, (value) => {
      if (!Array.isArray(value)) return null;
      return value.filter(
        (item): item is LocalFeedback =>
          isRecord(item) &&
          typeof item['runId'] === 'string' &&
          (item['rating'] === 'up' || item['rating'] === 'down') &&
          (item['reason'] === null || typeof item['reason'] === 'string') &&
          typeof item['at'] === 'number',
      );
    }) ?? []
  );
}

export function upsertFeedback(
  current: readonly LocalFeedback[],
  next: LocalFeedback,
): readonly LocalFeedback[] {
  const merged = [next, ...current.filter((item) => item.runId !== next.runId)].slice(0, MAX_STORED);
  writeJson(KEYS.feedback, merged);
  return merged;
}

/** One line, trimmed, capped — the same rule the backend applies. */
export function cleanReason(text: string): string | null {
  const cleaned = text.split(/\s+/).filter(Boolean).join(' ').slice(0, MAX_REASON);
  return cleaned || null;
}
