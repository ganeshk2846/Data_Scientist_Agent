import { Suspense, lazy, useState } from 'react';
import { ChevronRight } from 'lucide-react';

import { LookupTable } from './LookupTable';
import { Tag } from '@/components/briefing/StatusBadge';
import { useLineage, useLineageHandlers } from '@/components/briefing/LineageContext';
import { SqlBlock } from '@/components/queries/SqlBlock';
import { CopyButton } from '@/components/queries/QueryList';
import { Card, Hairline, SectionLabel } from '@/components/ui/Card';
import { CountUp } from '@/components/ui/CountUp';
import { SkeletonBlock } from '@/components/ui/Skeleton';
import {
  asAnalystOutput,
  asAnomalyResult,
  asDriverResult,
  asLookup,
  deriveSeries,
} from '@/lib/evidence';
import { asHeroFigure, disambiguateTitles, evidenceTitle } from '@/lib/evidenceTitle';
import { cx } from '@/lib/cx';
import { formatDuration, humanise } from '@/lib/format';
import type { ResolvedTheme } from '@/lib/theme';
import type { AnswerEnvelope, EvidenceBlock } from '@/types/envelope';

/**
 * Recharts is ~420 kB. A lookup-only run — the common case — should never pay
 * for it, so the two chart modules load on demand behind a shaped skeleton.
 */
const AnomalyChart = lazy(() =>
  import('./AnomalyChart').then((module) => ({ default: module.AnomalyChart })),
);
const DriverBars = lazy(() =>
  import('./DriverBars').then((module) => ({ default: module.DriverBars })),
);

interface EvidenceSectionProps {
  envelope: AnswerEnvelope;
  theme: ResolvedTheme;
}

export function EvidenceSection({ envelope, theme }: EvidenceSectionProps) {
  const { evidence } = envelope;
  if (evidence.length === 0) return null;

  const series = deriveSeries(evidence);
  const titles = disambiguateTitles(
    evidence.map((block) => evidenceTitle(envelope, block, asLookup(block))),
  );

  return (
    <section data-print="flow">
      <SectionLabel>Evidence</SectionLabel>
      <div className="mt-4 space-y-5">
        {evidence.map((block, index) => (
          <EvidenceCard
            key={`${block.module}-${index}`}
            block={block}
            envelope={envelope}
            title={titles[index] ?? { title: 'Evidence', period: null }}
            series={series}
            theme={theme}
          />
        ))}
      </div>
    </section>
  );
}

function EvidenceCard({
  block,
  envelope,
  title,
  series,
  theme,
}: {
  block: EvidenceBlock;
  envelope: AnswerEnvelope;
  title: { title: string; period: string | null };
  series: ReturnType<typeof deriveSeries>;
  theme: ResolvedTheme;
}) {
  const analyst = asAnalystOutput(block);
  const anomaly = asAnomalyResult(block);
  const driver = asDriverResult(block);
  const lookup = asLookup(block);
  const hero = lookup ? asHeroFigure(lookup) : null;

  const lineage = useLineage();
  const lit = lineage.isAnyClaimLit(block.source_claims);

  // The query this block came from — a lookup names it, an analyst lists it.
  const queryId = lookup?.query_id ?? analyst?.sources[0] ?? null;
  const query = queryId
    ? envelope.queries.find((candidate) => candidate.query_id === queryId)
    : undefined;

  const handlers = useLineageHandlers({
    claimIds: block.source_claims,
    sourceIds: queryId ? [queryId] : [],
  });

  const [sqlOpen, setSqlOpen] = useState(false);

  return (
    <Card
      tone="flat"
      className={cx(
        'edge-gold sheen overflow-hidden transition-[border-color,box-shadow] duration-micro ease-editorial',
        lit && 'border-gold shadow-lifted',
      )}
      {...handlers}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 px-5 pt-5 sm:px-7 sm:pt-6">
        <div className="min-w-0">
          {title.period ? (
            <div className="text-micro uppercase tracking-label text-ink-faint">
              {title.period}
            </div>
          ) : null}
          <h3 className="mt-1.5 font-serif text-[1.25rem] leading-snug text-ink">
            {title.title}
          </h3>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {analyst && analyst.status !== 'ok' ? (
            <Tag tone="terracotta">{humanise(analyst.status)}</Tag>
          ) : null}

          {/* Claim chips: part of the lineage thread. */}
          {block.source_claims.map((claimId) => (
            <span
              key={claimId}
              className={cx(
                'font-mono text-[0.6875rem] transition-colors duration-micro',
                lineage.isClaimLit(claimId) ? 'text-gold-ink' : 'text-ink-faint',
              )}
            >
              {claimId}
            </span>
          ))}

          {/* The query label reveals that card's SQL inline. */}
          {query ? (
            <button
              type="button"
              onClick={() => setSqlOpen((value) => !value)}
              aria-expanded={sqlOpen}
              data-print="hide"
              className={cx(
                'inline-flex items-center gap-1 rounded-[3px] border px-2 py-0.5',
                'font-mono text-[0.6875rem] transition-colors duration-micro ease-editorial',
                sqlOpen || lineage.isSourceLit(query.query_id)
                  ? 'border-gold text-gold-ink'
                  : 'border-hairline text-ink-faint hover:border-gold hover:text-gold-ink',
              )}
            >
              <ChevronRight
                size={10}
                strokeWidth={2}
                aria-hidden
                className={cx(
                  'transition-transform duration-micro ease-editorial',
                  sqlOpen && 'rotate-90',
                )}
              />
              {query.query_id}
            </button>
          ) : null}
        </div>
      </div>

      {/* Inline SQL reveal. */}
      {query && sqlOpen ? (
        <div className="mt-5 border-t border-hairline bg-[rgb(var(--c-bg-sunken)/0.5)] px-5 py-4 sm:px-7">
          <div className="mb-2.5 flex items-center justify-between gap-3">
            <span className="text-[0.6875rem] tabular-nums text-ink-faint">
              {query.origin} · {formatDuration(query.duration_ms)} · {query.status}
            </span>
            <CopyButton text={query.sql} />
          </div>
          <SqlBlock sql={query.sql} />
        </div>
      ) : null}

      <div className="px-5 pb-6 pt-5 sm:px-7 sm:pb-7">
        {/* A single-cell result is a headline number, not a table. */}
        {hero ? (
          <div>
            <CountUp
              value={hero.value}
              className="block font-serif text-[2.75rem] leading-[1.05] tracking-[-0.015em] text-ink sm:text-[3.75rem]"
            />
            <div className="mt-3 flex items-center gap-2.5">
              <span className="font-mono text-[0.6875rem] uppercase tracking-label text-ink-faint">
                {hero.unit}
              </span>
              <span aria-hidden className="h-2.5 w-px bg-hairline-strong" />
              <span className="font-mono text-[0.6875rem] text-ink-faint">{hero.type}</span>
            </div>
          </div>
        ) : null}

        {anomaly ? (
          <Suspense fallback={<SkeletonBlock className="h-56 w-full" />}>
            <AnomalyChart result={anomaly} series={series} theme={theme} />
          </Suspense>
        ) : null}

        {driver ? (
          <Suspense fallback={<SkeletonBlock className="h-56 w-full" />}>
            <DriverBars result={driver} />
          </Suspense>
        ) : null}

        {lookup && !hero ? <LookupTable output={lookup} /> : null}

        {/* An analyst that produced no result still explains itself. */}
        {analyst && !anomaly && !driver ? (
          <p className="text-small leading-relaxed text-ink-muted">
            {analyst.reason ?? 'This module produced no result.'}
          </p>
        ) : null}
        {!analyst && !lookup ? (
          <p className="text-small text-ink-muted">
            This evidence block did not match a known shape and has been left
            unrendered.
          </p>
        ) : null}

        {analyst && analyst.assumptions.length > 0 ? (
          <>
            <Hairline className="my-6" />
            <SectionLabel>Assumptions</SectionLabel>
            <ul className="mt-3 space-y-2">
              {analyst.assumptions.map((assumption) => (
                <li
                  key={assumption}
                  className="max-w-prose text-[0.75rem] leading-relaxed text-ink-faint"
                >
                  {assumption}
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </Card>
  );
}
