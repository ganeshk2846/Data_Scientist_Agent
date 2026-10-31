import { cx } from '@/lib/cx';

/**
 * The hero suggestions are the demo's single-question beats (docs/DEMO_SCRIPT.md),
 * WHY first: why, so what, what next, what if, now what, a compound question,
 * discovery, then the V1 chips. `scripts/verify_demo.py` replays every one live
 * against `/api/v2/ask` and fails if this list differs from `hero_chips` in
 * `scripts/demo_v2.yaml`, so a chip is always a question that has just passed.
 *
 * Every chip answers through `/api/v2/ask`. The V1 caveats still hold for the
 * last three: the anomaly route needs a governed metric and a window including
 * the year, and a bare month clarifies instead.
 */
export const SUGGESTIONS: readonly string[] = [
  'Why did revenue drop in the top category in April 2018?',
  'Why did order count fall in December 2017?',
  'Did the carrier cause the delivery delays?',
  'How far are we off the regional targets?',
  'Forecast revenue for the next 3 months',
  'What if we raise prices 5%?',
  'Which customer segment should we target?',
  'How does revenue trend look today and what will it be in 3 months?',
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
