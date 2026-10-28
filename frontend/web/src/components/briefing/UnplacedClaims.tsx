import { Tag } from './StatusBadge';
import { Card, SectionLabel } from '@/components/ui/Card';
import { Collapsible } from '@/components/ui/Collapsible';
import { CLAIM_KIND_LABEL, GRADE_LABEL } from '@/lib/claims';
import type { LedgerClaim } from '@/types/envelope';

/**
 * Claims the ledger approved whose numbers do not appear in the narrative —
 * the fact checker may have cut the sentence that used them. They still belong
 * in the briefing, since they are the evidence the run stands on.
 */
export function UnplacedClaims({ claims }: { claims: readonly LedgerClaim[] }) {
  if (claims.length === 0) return null;

  return (
    <Card tone="sunken" className="px-5 py-4">
      <Collapsible
        summary={
          <SectionLabel>
            Further claims
            <span aria-hidden className="mx-2 text-ink-faint/50">
              ·
            </span>
            <span className="normal-case tracking-normal">
              {claims.length} not cited in the narrative
            </span>
          </SectionLabel>
        }
      >
        <ul className="mt-4 space-y-4 pl-7">
          {claims.map((claim) => (
            <li key={claim.claim_id}>
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
                <span className="font-mono text-[0.6875rem] text-gold">
                  {claim.claim_id}
                </span>
                <Tag>{CLAIM_KIND_LABEL[claim.kind]}</Tag>
                <span className="text-[0.6875rem] text-ink-faint">
                  grade <span className="tabular-nums">{claim.grade}</span>
                  {GRADE_LABEL[claim.grade] ? ` · ${GRADE_LABEL[claim.grade]}` : null}
                </span>
                <span className="font-mono text-[0.6875rem] text-ink-faint">
                  {claim.source.type} · {claim.source.id}
                </span>
              </div>
              <p className="mt-1.5 max-w-prose text-small leading-relaxed text-ink-muted">
                {claim.text}
              </p>
              {claim.numbers.length > 0 ? (
                <p className="mt-1 font-mono text-[0.6875rem] tabular-nums text-ink-faint">
                  {claim.numbers.map((number) => number.token).join(', ')}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </Collapsible>
    </Card>
  );
}
