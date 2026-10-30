import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { useEffect, useState } from 'react';

import { SectionLabel } from '@/components/ui/Card';
import { useToast } from '@/components/ui/Toast';
import { cx } from '@/lib/cx';
import { MAX_REASON, type LocalFeedback } from '@/lib/feedback';
import type { FeedbackRating } from '@/types/v2';

/**
 * Was this answer useful? Thumbs up or down with an optional reason, on every
 * answer (Track 5, item 8). The reason box opens after a thumb is chosen, so
 * the common case is one click.
 */
export function FeedbackBar({
  runId,
  current,
  onRate,
}: {
  runId: string;
  current: LocalFeedback | undefined;
  onRate: (runId: string, rating: FeedbackRating, reason: string) => Promise<boolean>;
}) {
  const toast = useToast();
  const [rating, setRating] = useState<FeedbackRating | null>(current?.rating ?? null);
  const [reason, setReason] = useState(current?.reason ?? '');
  const [editing, setEditing] = useState(false);

  // A different answer on the canvas: show its own stored rating. Keyed on the
  // run alone, so saving a rating does not close the reason box it opens.
  useEffect(() => {
    setRating(current?.rating ?? null);
    setReason(current?.reason ?? '');
    setEditing(false);
  }, [runId]);

  const choose = (next: FeedbackRating) => {
    setRating(next);
    setEditing(true);
    void onRate(runId, next, reason).then((ok) =>
      ok ? toast.done('Thanks — feedback saved') : toast.fault('Saved here, but the server did not accept it'),
    );
  };

  const saveReason = () => {
    if (!rating) return;
    setEditing(false);
    void onRate(runId, rating, reason).then((ok) =>
      ok ? toast.done('Reason saved') : toast.fault('Saved here, but the server did not accept it'),
    );
  };

  return (
    <section data-print="hide" data-testid="feedback-bar">
      <SectionLabel>Was this answer useful?</SectionLabel>
      <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Rate this answer">
        {(
          [
            ['up', 'Useful', ThumbsUp],
            ['down', 'Not useful', ThumbsDown],
          ] as const
        ).map(([value, label, Icon]) => (
          <button
            key={value}
            type="button"
            aria-pressed={rating === value}
            onClick={() => choose(value)}
            className={cx(
              'inline-flex items-center gap-2 rounded-sm border px-3 py-1.5 text-[0.8125rem]',
              'transition-colors duration-hover ease-editorial',
              rating === value
                ? 'border-ink text-ink'
                : 'border-hairline text-ink-muted hover:border-hairline-strong hover:text-ink',
            )}
          >
            <Icon size={13} strokeWidth={1.5} aria-hidden />
            {label}
          </button>
        ))}
        {rating && !editing ? (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-[0.75rem] text-ink-faint underline-offset-2 hover:text-ink-muted hover:underline"
          >
            {current?.reason ? 'Edit reason' : 'Add a reason'}
          </button>
        ) : null}
      </div>
      {rating && editing ? (
        <form
          className="mt-3 flex max-w-xl flex-wrap items-start gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            saveReason();
          }}
        >
          <label className="sr-only" htmlFor={`feedback-reason-${runId}`}>
            Reason (optional)
          </label>
          <input
            id={`feedback-reason-${runId}`}
            value={reason}
            maxLength={MAX_REASON}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Optional: what was right or wrong?"
            className="min-w-0 flex-1 rounded-sm border border-hairline bg-surface px-3 py-1.5 text-[0.8125rem] text-ink placeholder:text-ink-faint"
          />
          <button
            type="submit"
            className="rounded-sm border border-hairline-strong px-3 py-1.5 text-[0.8125rem] text-ink hover:border-ink"
          >
            Save reason
          </button>
        </form>
      ) : null}
    </section>
  );
}
