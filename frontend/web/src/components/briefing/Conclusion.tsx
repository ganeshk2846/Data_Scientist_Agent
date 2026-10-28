import { useMemo, useState } from 'react';

import { Popover } from '@/components/ui/Popover';
import { Tag } from './StatusBadge';
import { CLAIM_KIND_LABEL, GRADE_LABEL, annotateNarrative } from '@/lib/claims';
import { cx } from '@/lib/cx';
import type { LedgerClaim } from '@/types/envelope';

interface ClaimMarkProps {
  claims: readonly LedgerClaim[];
  text: string;
  /** Set while this or any sibling mark for the same claim is active. */
  highlighted: boolean;
  onHover: (claimIds: readonly string[] | null) => void;
}

/**
 * A number in the narrative, with its claim ids as small gold superscripts.
 * Hovering or focusing it highlights the number and opens the source popover;
 * the whole thing is a button so keyboard users get the same affordance.
 */
function ClaimMark({ claims, text, highlighted, onHover }: ClaimMarkProps) {
  const [open, setOpen] = useState(false);
  const ids = claims.map((claim) => claim.claim_id);

  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        onMouseEnter={() => {
          onHover(ids);
          setOpen(true);
        }}
        onMouseLeave={() => {
          onHover(null);
          setOpen(false);
        }}
        onFocus={() => {
          onHover(ids);
          setOpen(true);
        }}
        onBlur={() => {
          onHover(null);
          setOpen(false);
        }}
        aria-label={`${text}, supported by ${ids.join(', ')}`}
        className={cx(
          'rounded-[2px] px-0.5 transition-colors duration-micro ease-editorial',
          'decoration-gold/40 underline-offset-4',
          highlighted ? 'bg-[var(--c-gold-wash)] text-ink' : 'text-ink underline',
        )}
      >
        <span className="tabular-nums">{text}</span>
        <sup className="ml-0.5 font-sans text-[0.5625rem] font-medium tracking-wide text-gold">
          {ids.join(',')}
        </sup>
      </button>

      <Popover open={open} onClose={() => setOpen(false)}>
        <ul className="space-y-4">
          {claims.map((claim) => (
            <li key={claim.claim_id}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-mono text-[0.6875rem] text-gold">
                  {claim.claim_id}
                </span>
                <Tag>{CLAIM_KIND_LABEL[claim.kind]}</Tag>
              </div>
              <p className="mt-2 text-small leading-relaxed text-ink">{claim.text}</p>
              <dl className="mt-3 space-y-1.5 text-[0.6875rem] text-ink-faint">
                <div className="flex gap-2">
                  <dt className="w-14 shrink-0 uppercase">Source</dt>
                  <dd className="font-mono text-ink-muted">
                    {claim.source.type} · {claim.source.id}
                  </dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-14 shrink-0 uppercase">Grade</dt>
                  <dd className="text-ink-muted">
                    <span className="tabular-nums">{claim.grade}</span>
                    {GRADE_LABEL[claim.grade] ? ` · ${GRADE_LABEL[claim.grade]}` : null}
                  </dd>
                </div>
                {claim.numbers.length > 0 ? (
                  <div className="flex gap-2">
                    <dt className="w-14 shrink-0 uppercase">Numbers</dt>
                    <dd className="font-mono tabular-nums text-ink-muted">
                      {claim.numbers.map((number) => number.token).join(', ')}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </li>
          ))}
        </ul>
      </Popover>
    </span>
  );
}

interface ConclusionProps {
  conclusion: string;
  claims: readonly LedgerClaim[];
}

/** The headline narrative, in serif, with its numbers linked to the ledger. */
export function Conclusion({ conclusion, claims }: ConclusionProps) {
  const [active, setActive] = useState<readonly string[] | null>(null);
  const segments = useMemo(
    () => annotateNarrative(conclusion, claims),
    [conclusion, claims],
  );

  return (
    <p className="max-w-prose font-serif text-h2 font-light leading-[1.55] text-ink">
      {segments.map((segment, index) =>
        segment.kind === 'text' ? (
          <span key={index}>{segment.text}</span>
        ) : (
          <ClaimMark
            key={index}
            text={segment.text}
            claims={segment.claims}
            highlighted={
              !!active && segment.claims.some((claim) => active.includes(claim.claim_id))
            }
            onHover={setActive}
          />
        ),
      )}
    </p>
  );
}
