import { motion } from 'framer-motion';
import { useMemo, type ReactNode } from 'react';

import {
  CaveatCallout,
  NextActions,
  RouteStrip,
  RunMetricsFooter,
  ScopeLine,
} from './BriefingParts';
import { BriefingToolbar } from './BriefingToolbar';
import { Conclusion } from './Conclusion';
import { FollowUps } from './FollowUps';
import { LineageProvider } from './LineageContext';
import { StatusBadge } from './StatusBadge';
import { TrustPanel } from './TrustPanel';
import { UnplacedClaims } from './UnplacedClaims';
import { EvidenceSection } from '@/components/evidence/EvidenceSection';
import { QueryList, ReadOnlyNote } from '@/components/queries/QueryList';
import { Card, Hairline, SectionLabel } from '@/components/ui/Card';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { annotateNarrative, unplacedClaims } from '@/lib/claims';
import { buildFollowUps } from '@/lib/followUps';
import { formatWindow, humanise } from '@/lib/format';
import type { ResolvedTheme } from '@/lib/theme';
import type { AnswerEnvelope } from '@/types/envelope';

const EASE = [0.22, 0.61, 0.36, 1] as const;

/** Sections unfold one after another — slow, staggered, never bouncing. */
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
      data-print="flow"
      initial={reduced ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: reduced ? 0 : 0.55,
        delay: reduced ? 0 : index * 0.085,
        ease: EASE,
      }}
    >
      {children}
    </motion.div>
  );
}

interface BriefingProps {
  envelope: AnswerEnvelope;
  theme: ResolvedTheme;
  question: string | null;
  onAsk: (question: string) => void;
  onPresent: () => void;
  /** Presentation mode drops the chrome and shows only the briefing itself. */
  presenting?: boolean;
}

export function Briefing({
  envelope,
  theme,
  question,
  onAsk,
  onPresent,
  presenting = false,
}: BriefingProps) {
  const reduced = useReducedMotion();

  const segments = useMemo(
    () => annotateNarrative(envelope.conclusion ?? '', envelope.claims),
    [envelope.conclusion, envelope.claims],
  );
  const leftover = useMemo(
    () => unplacedClaims(segments, envelope.claims),
    [segments, envelope.claims],
  );
  const followUps = useMemo(() => buildFollowUps(envelope), [envelope]);

  // The run's SQL origin is stamped per run, so it is read once, here.
  const origin = envelope.queries[0]?.origin ?? null;
  const period = formatWindow(envelope.scope.window);
  const sqlHeading = envelope.scope.metric
    ? `${humanise(envelope.scope.metric)}${period ? ` · ${period}` : ''}`
    : null;

  let step = 0;
  const next = () => step++;

  const hasScope =
    !!envelope.scope.metric ||
    !!envelope.scope.window ||
    !!envelope.scope.grain ||
    envelope.scope.filters.length > 0 ||
    envelope.scope.governed;

  return (
    <LineageProvider>
      <div className={presenting ? 'space-y-14' : 'space-y-12'}>
        {/* ── The conclusion. Everything else supports this. ───────────── */}
        <Section index={next()} reduced={reduced}>
          <Card
            tone="flat"
            className="edge-gold sheen px-6 py-7 sm:px-10 sm:py-9"
            as="article"
          >
            <div className="flex flex-wrap items-center justify-between gap-x-5 gap-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <StatusBadge status={envelope.status} />
                {period ? (
                  <span className="text-micro uppercase tracking-label text-ink-faint">
                    {period}
                  </span>
                ) : null}
              </div>
              {!presenting ? (
                <BriefingToolbar
                  envelope={envelope}
                  question={question}
                  onPresent={onPresent}
                />
              ) : null}
            </div>

            {envelope.conclusion ? (
              <Conclusion
                conclusion={envelope.conclusion}
                claims={envelope.claims}
                className="mt-7"
              />
            ) : (
              <p className="mt-7 max-w-prose font-serif text-body-serif font-light text-ink-muted">
                This run produced no narrative conclusion.
              </p>
            )}

            <Hairline className="my-8" />
            <RouteStrip route={envelope.route} status={envelope.status} />

            {hasScope ? (
              <>
                <Hairline className="my-8" />
                <SectionLabel className="mb-4">Scope</SectionLabel>
                <ScopeLine scope={envelope.scope} />
              </>
            ) : null}
          </Card>
        </Section>

        {/* ── How this was computed. A first-class section, expanded. ───── */}
        {envelope.queries.length > 0 ? (
          <Section index={next()} reduced={reduced}>
            <QueryList
              queries={envelope.queries}
              claims={envelope.claims}
              origin={origin}
              {...(sqlHeading ? { heading: sqlHeading } : {})}
            />
            <div className="mt-4">
              <ReadOnlyNote />
            </div>
          </Section>
        ) : null}

        {/* ── Evidence. ─────────────────────────────────────────────────── */}
        {envelope.evidence.length > 0 ? (
          <Section index={next()} reduced={reduced}>
            <EvidenceSection envelope={envelope} theme={theme} />
          </Section>
        ) : null}

        {leftover.length > 0 ? (
          <Section index={next()} reduced={reduced}>
            <UnplacedClaims claims={leftover} />
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

        {/* ── Trust, then what to ask next. ─────────────────────────────── */}
        <Section index={next()} reduced={reduced}>
          <TrustPanel envelope={envelope} />
        </Section>

        {!presenting && followUps.length > 0 ? (
          <Section index={next()} reduced={reduced}>
            <FollowUps followUps={followUps} onAsk={onAsk} />
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
    </LineageProvider>
  );
}
