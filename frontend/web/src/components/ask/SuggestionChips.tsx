import { cx } from '@/lib/cx';

/**
 * The hero suggestions, in the demo order: the WHY questions lead, then the
 * rest of the V2 must-answer set (spec/v2/scope.md §7) — so what, what next,
 * what if, now what, discovery — then the four V1 chips, kept unchanged.
 *
 * Every chip answers through `/api/v2/ask`. The V1 caveats still hold for the
 * last four: the anomaly route needs a governed metric and a window including
 * the year, and a bare month clarifies instead.
 */
export const SUGGESTIONS: readonly string[] = [
  'Why did revenue drop in the top category in April 2018?',
  'Why did revenue spike in May 2018?',
  'How much did the April 2018 drop cost us?',
  'Forecast revenue for the next 3 months',
  'What if we raise prices 5%?',
  'Which customer segment should we target?',
  'What data do you have?',
  'How many orders were there in August 2018?',
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
