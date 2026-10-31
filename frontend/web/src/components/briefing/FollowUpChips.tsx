import { ArrowUpRight } from 'lucide-react';

import { SectionLabel } from '@/components/ui/Card';
import { humanise } from '@/lib/format';
import type { FollowUpSuggestion } from '@/types/v2';

/**
 * The backend's `follow_ups`, rendered verbatim (build-plan Track 5, item 4).
 * Each one was verified answerable before it was offered (EN-5). Nothing is
 * rendered when the list is empty — no local templating fills the gap.
 */
export function FollowUpChips({
  followUps,
  onAsk,
}: {
  followUps: readonly FollowUpSuggestion[];
  onAsk: (question: string) => void;
}) {
  if (followUps.length === 0) return null;
  return (
    <section data-print="hide">
      <SectionLabel>Continue</SectionLabel>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2" data-testid="follow-up-chips">
        {followUps.map((item) => (
          <li key={item.text}>
            <button
              type="button"
              onClick={() => onAsk(item.text)}
              className="edge-light group flex h-full w-full flex-col items-start gap-2 rounded-sm border border-hairline bg-surface px-4 py-3.5 text-left transition-[border-color,box-shadow] duration-micro ease-editorial hover:border-hairline-strong hover:shadow-soft"
            >
              <span className="text-micro uppercase tracking-label text-ink-faint">
                {humanise(item.intent)}
              </span>
              <span className="flex w-full items-start justify-between gap-3">
                <span className="font-serif text-[0.9375rem] leading-snug text-ink">{item.text}</span>
                <ArrowUpRight size={13} strokeWidth={1.5} aria-hidden className="mt-0.5 shrink-0 text-ink-faint" />
              </span>
              <span className="text-[0.75rem] leading-relaxed text-ink-faint">{item.rationale}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
