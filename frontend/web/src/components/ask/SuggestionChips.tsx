import { cx } from '@/lib/cx';

/** The four approved starting questions, in the brief's order. */
export const SUGGESTIONS: readonly string[] = [
  'How many orders were there in August 2018?',
  'Why did revenue drop in August?',
  "What's driving shipping delays?",
  'Revenue by state last quarter',
];

interface SuggestionChipsProps {
  onPick: (question: string) => void;
  disabled?: boolean;
}

export function SuggestionChips({ onPick, disabled = false }: SuggestionChipsProps) {
  return (
    <ul className="flex flex-wrap gap-2.5">
      {SUGGESTIONS.map((question) => (
        <li key={question}>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onPick(question)}
            className={cx(
              'rounded-full border border-hairline-strong bg-surface px-4 py-2',
              'text-small text-ink-muted',
              'transition-colors duration-micro ease-editorial',
              'hover:border-gold hover:bg-[var(--c-gold-wash)] hover:text-ink',
              'disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-hairline-strong',
              'disabled:hover:bg-surface disabled:hover:text-ink-muted',
            )}
          >
            {question}
          </button>
        </li>
      ))}
    </ul>
  );
}
