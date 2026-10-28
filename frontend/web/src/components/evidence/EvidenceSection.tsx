import { Suspense, lazy } from 'react';

import { LookupTable } from './LookupTable';
import { Tag } from '@/components/briefing/StatusBadge';
import { Card, Hairline, SectionLabel } from '@/components/ui/Card';
import {
  asAnalystOutput,
  asAnomalyResult,
  asDriverResult,
  asLookup,
  deriveSeries,
} from '@/lib/evidence';
import { SkeletonBlock } from '@/components/ui/Skeleton';
import { humanise } from '@/lib/format';
import type { ResolvedTheme } from '@/lib/theme';
import type { EvidenceBlock } from '@/types/envelope';

/**
 * Recharts is ~550 kB. A lookup-only run — the common case — should never pay
 * for it, so the two chart modules load on demand behind a shaped skeleton.
 */
const AnomalyChart = lazy(() =>
  import('./AnomalyChart').then((module) => ({ default: module.AnomalyChart })),
);
const DriverBars = lazy(() =>
  import('./DriverBars').then((module) => ({ default: module.DriverBars })),
);

const MODULE_TITLE: Record<EvidenceBlock['module'], string> = {
  lookup: 'Query result',
  anomaly: 'Anomaly detection',
  driver: 'Driver attribution',
  risk: 'Risk assessment',
};

interface EvidenceSectionProps {
  evidence: readonly EvidenceBlock[];
  theme: ResolvedTheme;
}

export function EvidenceSection({ evidence, theme }: EvidenceSectionProps) {
  if (evidence.length === 0) return null;
  const series = deriveSeries(evidence);

  return (
    <section>
      <SectionLabel>Evidence</SectionLabel>
      <div className="mt-4 space-y-5">
        {evidence.map((block, index) => (
          <EvidenceCard
            key={`${block.module}-${index}`}
            block={block}
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
  series,
  theme,
}: {
  block: EvidenceBlock;
  series: ReturnType<typeof deriveSeries>;
  theme: ResolvedTheme;
}) {
  const analyst = asAnalystOutput(block);
  const anomaly = asAnomalyResult(block);
  const driver = asDriverResult(block);
  const lookup = asLookup(block);

  return (
    <Card className="p-5 sm:p-7">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h3 className="text-h3 font-sans text-ink">{MODULE_TITLE[block.module]}</h3>
        <div className="flex flex-wrap items-center gap-2">
          {analyst && analyst.status !== 'ok' ? (
            <Tag tone="terracotta">{humanise(analyst.status)}</Tag>
          ) : null}
          {block.source_claims.map((claimId) => (
            <span key={claimId} className="font-mono text-[0.6875rem] text-gold">
              {claimId}
            </span>
          ))}
        </div>
      </div>

      <Hairline className="my-5" />

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
      {lookup ? <LookupTable output={lookup} /> : null}

      {/* An analyst that produced no result still explains itself. */}
      {analyst && !anomaly && !driver ? (
        <p className="text-small leading-relaxed text-ink-muted">
          {analyst.reason ?? 'This module produced no result.'}
        </p>
      ) : null}
      {!analyst && !lookup ? (
        <p className="text-small text-ink-muted">
          This evidence block did not match a known shape and has been left unrendered.
        </p>
      ) : null}

      {analyst && analyst.assumptions.length > 0 ? (
        <>
          <Hairline className="my-5" />
          <SectionLabel>Assumptions</SectionLabel>
          <ul className="mt-2.5 space-y-1.5">
            {analyst.assumptions.map((assumption) => (
              <li
                key={assumption}
                className="text-[0.6875rem] leading-relaxed text-ink-faint"
              >
                {assumption}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Card>
  );
}
