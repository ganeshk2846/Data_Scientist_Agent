import { CornerDownRight } from 'lucide-react';

import { humanise } from '@/lib/format';

/**
 * The "interpreted as" chip (Track 5, item 3; RQ-2: inheritance is never
 * silent). Shows the backend's own rewritten question and the fields it
 * carried from the earlier turn — nothing is paraphrased here.
 */
export function InterpretedAs({
  text,
  inherited,
}: {
  text: string | null;
  inherited: readonly string[];
}) {
  if (!text && inherited.length === 0) return null;
  return (
    <div
      className="inline-flex max-w-full flex-wrap items-center gap-x-2.5 gap-y-1 rounded-sm border border-hairline bg-sunken px-3 py-1.5"
      data-testid="interpreted-as"
    >
      <CornerDownRight size={12} strokeWidth={1.5} aria-hidden className="text-ink-faint" />
      {text ? (
        <span className="text-[0.75rem] text-ink-muted">
          Interpreted as <span className="text-ink">“{text}”</span>
        </span>
      ) : null}
      {inherited.length > 0 ? (
        <span className="text-[0.6875rem] text-ink-faint">
          Carried from your previous question: {inherited.map(humanise).join(', ')}
        </span>
      ) : null}
    </div>
  );
}
