import { Check } from 'lucide-react';

import { SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';

/** What a V2 clarification offers, from the envelope or the live `clarify` event. */
export interface ClarifyChoice {
  question: string;
  options: readonly { option_id: string; label: string; detail: string | null }[];
  defaultOptionId: string | null;
  defaultRationale: string | null;
  round: 1 | 2;
}

/** The clarification cap (CL-4): the backend asks at most twice, then applies the default. */
export const MAX_CLARIFY_ROUNDS = 2;

/**
 * The clarification's options as real buttons, with the default stated
 * (Track 5, item 4; build-plan §7 work item 6). Choosing one sends its
 * `option_id`, which the backend applies deterministically (CL-6). The
 * free-text reply box beneath stays as the escape hatch.
 */
export function ClarifyOptions({
  choice,
  onChoose,
}: {
  choice: ClarifyChoice;
  onChoose: (optionId: string, label: string) => void;
}) {
  const fallback = choice.options.find((option) => option.option_id === choice.defaultOptionId);
  return (
    <div data-testid="clarify-options">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <SectionLabel>{choice.question}</SectionLabel>
        <span className="text-[0.6875rem] tabular-nums text-ink-faint" data-testid="clarify-round">
          Round {choice.round} of {MAX_CLARIFY_ROUNDS}
        </span>
      </div>
      <ul className="mt-3 flex flex-wrap gap-2">
        {choice.options.map((option) => {
          const isDefault = option.option_id === choice.defaultOptionId;
          return (
            <li key={option.option_id}>
              <button
                type="button"
                onClick={() => onChoose(option.option_id, option.label)}
                className={cx(
                  'flex flex-col items-start rounded-sm border px-3.5 py-2 text-left',
                  'transition-[border-color,background-color] duration-micro ease-editorial',
                  isDefault
                    ? 'border-hairline-strong bg-surface'
                    : 'border-hairline bg-surface hover:border-hairline-strong',
                  'hover:bg-[var(--c-accent-wash)]',
                )}
              >
                <span className="inline-flex items-center gap-1.5 text-small text-ink">
                  {isDefault ? <Check size={12} strokeWidth={2} aria-hidden /> : null}
                  {option.label}
                  {isDefault ? <span className="sr-only"> (the default)</span> : null}
                </span>
                {option.detail ? (
                  <span className="mt-0.5 text-[0.75rem] text-ink-faint">{option.detail}</span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
      {fallback ? (
        <p className="mt-3 max-w-prose text-[0.8125rem] leading-relaxed text-ink-muted" data-testid="clarify-default">
          If you say nothing more, the answer assumes <span className="text-ink">{fallback.label}</span>
          {choice.defaultRationale ? <> — {choice.defaultRationale}</> : '.'}
        </p>
      ) : null}
    </div>
  );
}
