import { ArrowUpRight } from 'lucide-react';

import { SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import { FOLLOW_UP_CAPTION, type FollowUp } from '@/lib/followUps';

/**
 * Suggested next questions. These are templates filled from `scope`, not
 * insights — see `lib/followUps.ts` for the rule that keeps them answerable.
 */
export function FollowUps({
  followUps,
  onAsk,
}: {
  followUps: readonly FollowUp[];
  onAsk: (question: string) => void;
}) {
  if (followUps.length === 0) return null;

  return (
    <section data-print="hide">
      <SectionLabel>Continue</SectionLabel>
      <ul
        className={cx(
          'mt-4 grid gap-3',
          followUps.length >= 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2',
        )}
      >
        {followUps.map((followUp) => (
          <li key={followUp.question}>
            <button
              type="button"
              onClick={() => onAsk(followUp.question)}
              className={cx(
                'edge-gold group flex h-full w-full flex-col items-start gap-3 rounded-[3px]',
                'border border-hairline bg-surface px-4 py-3.5 text-left',
                'transition-[border-color,box-shadow,background-color] duration-micro ease-editorial',
                'hover:border-gold hover:shadow-soft',
              )}
            >
              <span className="text-micro uppercase tracking-label text-ink-faint">
                {FOLLOW_UP_CAPTION[followUp.kind]}
              </span>
              <span className="flex w-full flex-1 items-start justify-between gap-3">
                <span className="font-serif text-[0.9375rem] leading-snug text-ink">
                  {followUp.question}
                </span>
                <ArrowUpRight
                  size={13}
                  strokeWidth={1.75}
                  aria-hidden
                  className="mt-0.5 shrink-0 text-ink-faint transition-colors duration-micro group-hover:text-gold"
                />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
