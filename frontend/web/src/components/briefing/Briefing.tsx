import { motion } from 'framer-motion';
import { useMemo, type ReactNode } from 'react';

import {
  BriefingHeader,
  CaveatCallout,
  NextActions,
  RouteStrip,
  RunMetricsFooter,
  ScopeLine,
} from './BriefingParts';
import { Conclusion } from './Conclusion';
import { UnplacedClaims } from './UnplacedClaims';
import { EvidenceSection } from '@/components/evidence/EvidenceSection';
import { QueryList } from '@/components/queries/QueryList';
import { Card, Hairline, SectionLabel } from '@/components/ui/Card';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { annotateNarrative, unplacedClaims } from '@/lib/claims';
import type { ResolvedTheme } from '@/lib/theme';
import type { AnswerEnvelope } from '@/types/envelope';

/** Sections fade up one after another, slowly, never bouncing. */
function Section({
  children,
  index,
  reduced,
}: {
  children: ReactNode;
  index: number;
  reduced: boolean;
}) {
  return (
    <motion.div
      initial={reduced ? false : { opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: reduced ? 0 : 0.5,
        delay: reduced ? 0 : index * 0.09,
        ease: [0.22, 0.61, 0.36, 1],
      }}
    >
      {children}
    </motion.div>
  );
}

interface BriefingProps {
  envelope: AnswerEnvelope;
  theme: ResolvedTheme;
}

/** The answer, laid out as an executive briefing. */
export function Briefing({ envelope, theme }: BriefingProps) {
  const reduced = useReducedMotion();

  const segments = useMemo(
    () => annotateNarrative(envelope.conclusion ?? '', envelope.claims),
    [envelope.conclusion, envelope.claims],
  );
  const leftover = useMemo(
    () => unplacedClaims(segments, envelope.claims),
    [segments, envelope.claims],
  );

  // The run's SQL origin is stamped per run, so it is read once here.
  const origin = envelope.queries[0]?.origin ?? null;

  let step = 0;
  const next = () => step++;

  return (
    <div className="space-y-10">
      <Section index={next()} reduced={reduced}>
        <Card className="p-6 sm:p-9">
          <BriefingHeader envelope={envelope} />

          {envelope.conclusion ? (
            <div className="mt-6">
              <Conclusion conclusion={envelope.conclusion} claims={envelope.claims} />
            </div>
          ) : (
            <p className="mt-6 max-w-prose font-serif text-body-serif font-light text-ink-muted">
              This run produced no narrative conclusion.
            </p>
          )}

          <Hairline className="my-7" />
          <RouteStrip route={envelope.route} status={envelope.status} />

          {envelope.scope.metric ||
          envelope.scope.window ||
          envelope.scope.grain ||
          envelope.scope.filters.length > 0 ||
          envelope.scope.governed ? (
            <>
              <Hairline className="my-7" />
              <SectionLabel className="mb-4">Scope</SectionLabel>
              <ScopeLine scope={envelope.scope} />
            </>
          ) : null}
        </Card>
      </Section>

      {leftover.length > 0 ? (
        <Section index={next()} reduced={reduced}>
          <UnplacedClaims claims={leftover} />
        </Section>
      ) : null}

      {envelope.evidence.length > 0 ? (
        <Section index={next()} reduced={reduced}>
          <EvidenceSection evidence={envelope.evidence} theme={theme} />
        </Section>
      ) : null}

      {envelope.queries.length > 0 ? (
        <Section index={next()} reduced={reduced}>
          <QueryList queries={envelope.queries} origin={origin} />
        </Section>
      ) : null}

      {envelope.caveats.length > 0 || envelope.causal_boundary_note ? (
        <Section index={next()} reduced={reduced}>
          <CaveatCallout
            caveats={envelope.caveats}
            causalBoundaryNote={envelope.causal_boundary_note}
          />
        </Section>
      ) : null}

      {envelope.next_actions.length > 0 ? (
        <Section index={next()} reduced={reduced}>
          <NextActions actions={envelope.next_actions} />
        </Section>
      ) : null}

      <Section index={next()} reduced={reduced}>
        <RunMetricsFooter
          metrics={envelope.run_metrics}
          method={envelope.method}
          provenance={envelope.provenance}
          contractVersion={envelope.contract_version}
        />
      </Section>
    </div>
  );
}
