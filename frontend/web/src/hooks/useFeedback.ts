import { useCallback, useState } from 'react';

import { postFeedback } from '@/lib/api';
import { cleanReason, loadFeedback, upsertFeedback, type LocalFeedback } from '@/lib/feedback';
import type { FeedbackRating } from '@/types/v2';

export interface FeedbackController {
  ratingFor: (runId: string) => LocalFeedback | undefined;
  /** Resolves true once stored; live, also once the backend accepted it. */
  rate: (runId: string, rating: FeedbackRating, reason: string) => Promise<boolean>;
}

/**
 * Thumbs up / down per answer, stored per session (Track 5, item 8). Mock
 * mode keeps it in this browser only; live mode also posts it to the
 * backend, owner-scoped by the bearer token.
 */
export function useFeedback(sessionId: string, mock: boolean): FeedbackController {
  const [items, setItems] = useState<readonly LocalFeedback[]>(loadFeedback);

  const ratingFor = useCallback(
    (runId: string) => items.find((item) => item.runId === runId),
    [items],
  );

  const rate = useCallback(
    async (runId: string, rating: FeedbackRating, reasonText: string) => {
      const reason = cleanReason(reasonText);
      setItems((current) => upsertFeedback(current, { runId, rating, reason, at: Date.now() }));
      if (mock) return true;
      try {
        await postFeedback({ sessionId, runId, rating, reason });
        return true;
      } catch {
        return false;
      }
    },
    [mock, sessionId],
  );

  return { ratingFor, rate };
}
