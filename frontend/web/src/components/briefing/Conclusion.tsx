import { useMemo, useState } from 'react';

import { Popover } from '@/components/ui/Popover';
import { Tag } from './StatusBadge';
import { useLineage, useLineageHandlers } from './LineageContext';
import { CLAIM_KIND_LABEL, GRADE_LABEL, annotateNarrative } from '@/lib/claims';
import { cx } from '@/lib/cx';
import type { LedgerClaim } from '@/types/envelope';

interface ClaimMarkProps {
  claims: readonly LedgerClaim[];
  text: string;
}

/**
 * A number in the narrative, with its claim ids as gold superscripts.
 *
 * Hovering or focusing it lights the whole lineage — this number, its evidence
 * card and the query behind it — and opens the source popover. It is a real
 * button, so the keyboard gets the same affordance as the pointer.
 */
function ClaimMark({ claims, text }: ClaimMarkProps) {
  const [open, setOpen] = useState(false);
  const lineage = useLineage();
  const ids = claims.map((claim) => claim.claim_id);
  const lit = ids.some((id) => lineage.isClaimLit(id));

  const handlers = useLineageHandlers({
    claimIds: ids,
    sourceIds: claims.map((claim) => claim.source.id),
  });

  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        onMouseEnter={() => {
          handlers.onMouseEnter();
          setOpen(true);
        }}
        onMouseLeave={() => {
          handlers.onMouseLeave();
          setOpen(false);
        }}
        onFocus={() => {
          handlers.onFocus();
          setOpen(true);
        }}
        onBlur={() => {
          handlers.onBlur();
          setOpen(false);
        }}
        className={cx(
          'relative rounded-[2px] px-0.5 transition-[background-color,box-shadow] duration-micro ease-editorial',
          // The faint glow is the "this is live" tell; it never shifts layout.
          lit
            ? 'bg-[var(--c-gold-wash)] text-ink shadow-[0_0_0_1px_rgb(var(--c-gold)/0.35)]'
            : 'text-ink',
        )}
      >
        <span
          className={cx(
            'tabular-nums decoration-1 underline-offset-[5px]',
            lit ? 'no-underline' : 'underline decoration-[rgb(var(--c-gold)/0.35)]',
          )}
        >
          {text}
        </span>
        {/* The accessible name is built from the button's own content rather
            than an aria-label: a label that merely restates visible text can
            only drift from it, and screen readers then disagree with the page. */}
        <sup
          aria-hidden
          className={cx(
            'ml-0.5 font-sans text-[0.5625rem] font-medium tracking-wide transition-colors duration-micro',
            lit ? 'text-gold-ink' : 'text-gold-ink/90',
          )}
        >
          {ids.join(',')}
        </sup>
        <span className="sr-only">, supported by {ids.join(', ')}</span>
      </button>

      <Popover open={open} onClose={() => setOpen(false)}>
        <ul className="space-y-4">
          {claims.map((claim) => (
            <li key={claim.claim_id}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-mono text-[0.6875rem] text-gold-ink">
                  {claim.claim_id}
                </span>
                <Tag>{CLAIM_KIND_LABEL[claim.kind]}</Tag>
              </div>
              <p className="mt-2 text-small leading-relaxed text-ink">{claim.text}</p>
              <dl className="mt-3 space-y-1.5 text-[0.6875rem] text-ink-faint">
                <div className="flex gap-2">
                  <dt className="w-14 shrink-0 uppercase tracking-label">Source</dt>
                  <dd className="font-mono text-ink-muted">
                    {claim.source.type} · {claim.source.id}
                  </dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-14 shrink-0 uppercase tracking-label">Grade</dt>
                  <dd className="text-ink-muted">
                    <span className="tabular-nums">{claim.grade}</span>
                    {GRADE_LABEL[claim.grade] ? ` · ${GRADE_LABEL[claim.grade]}` : null}
                  </dd>
                </div>
                {claim.numbers.length > 0 ? (
                  <div className="flex gap-2">
                    <dt className="w-14 shrink-0 uppercase tracking-label">Numbers</dt>
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

/** The headline narrative, in serif, with its numbers linked to the ledger. */
export function Conclusion({
  conclusion,
  claims,
  className,
}: {
  conclusion: string;
  claims: readonly LedgerClaim[];
  className?: string;
}) {
  const segments = useMemo(
    () => annotateNarrative(conclusion, claims),
    [conclusion, claims],
  );

  return (
    <p
      className={cx(
        'max-w-prose font-serif font-light text-ink',
        'text-[1.5rem] leading-[1.5] tracking-[-0.011em] sm:text-[1.75rem] sm:leading-[1.48]',
        className,
      )}
    >
      {segments.map((segment, index) =>
        segment.kind === 'text' ? (
          <span key={index}>{segment.text}</span>
        ) : (
          <ClaimMark key={index} text={segment.text} claims={segment.claims} />
        ),
      )}
    </p>
  );
}
