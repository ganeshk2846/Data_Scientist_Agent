import { cx } from '@/lib/cx';

/**
 * Four questions verified to return a full `answered` briefing against the live
 * backend. Two governed lookups (one comparative, which runs two queries and
 * yields three claims) and two anomaly runs — one inside the normal range, one
 * outside it — so the banded chart is exercised in both verdicts.
 *
 * Every chip must stay verified. The anomaly route only answers when the
 * question names BOTH a governed metric (gmv, revenue, order_count, aov) and an
 * explicit time window including the year; drop the year and the router
 * clarifies instead. Driver questions are deliberately absent: the backend's
 * driver path currently raises, so every one of them returns `error`.
 */
export const SUGGESTIONS: readonly string[] = [
  'How many orders were there in August 2018?',
  'Why did revenue spike in November 2017?',
  'How did revenue in 2018 compare to 2017?',
  'Was order count unusual in August 2018?',
];

interface SuggestionChipsProps {
  onPick: (question: string) => void;
  disabled?: boolean;
}

export function SuggestionChips({ onPick, disabled = false }: SuggestionChipsProps) {
  return (
    <ul className="flex flex-wrap justify-center gap-2">
      {SUGGESTIONS.map((question) => (
        <li key={question}>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onPick(question)}
            className={cx(
              'rounded-sm border border-hairline bg-[rgb(var(--c-surface)/0.6)] px-3.5 py-2',
              'text-[0.8125rem] text-ink-muted backdrop-blur-sm',
              'transition-[color,border-color,background-color] duration-micro ease-editorial',
              'hover:border-accent hover:bg-[var(--c-accent-wash)] hover:text-ink',
              'disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-hairline-strong',
              'disabled:hover:border-hairline disabled:hover:text-ink-muted',
            )}
          >
            {question}
          </button>
        </li>
      ))}
    </ul>
  );
}
