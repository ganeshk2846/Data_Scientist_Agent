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

/**
 * The reveal.
 *
 * One cue per element, 95ms apart, in reading order — the status and period
 * first, then the conclusion, then the figure, then everything that supports
 * it. It is choreographed like a title sequence rather than fired all at once,
 * because that is the difference between a page appearing and a page being
 * *presented*: the eye is given the one sentence that matters before anything
 * else arrives to compete with it.
 *
 * 95ms is the midpoint of the 80–120ms band — fast enough that the whole
 * briefing is settled inside a second, slow enough to read as deliberate.
 */
const STEP = 0.095;

function Reveal({
  children,
  step,
  reduced,
  className,
}: {
  children: ReactNode;
  step: number;
  reduced: boolean;
  className?: string;
}) {
  return (
    <motion.div
      data-print="flow"
      className={className}
      initial={reduced ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: reduced ? 0 : 0.5,
        delay: reduced ? 0 : step * STEP,
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
  starred?: boolean;
  pinned?: boolean;
  canPin?: boolean;
  onToggleStar?: () => void;
  onPin?: () => void;
  onInspect?: () => void;
  /** Presentation mode drops the chrome and shows only the briefing itself. */
  presenting?: boolean;
}

export function Briefing({
  envelope,
  theme,
  question,
  onAsk,
  onPresent,
  starred = false,
  pinned = false,
  canPin = false,
  onToggleStar,
  onPin,
  onInspect,
  presenting = false,
}: BriefingProps) {
  const reduced = useReducedMotion();

  const segments = useMemo(
    () => annotateNarrative(envelope.conclusion ?? '', envelope.claims ?? []),
    [envelope.conclusion, envelope.claims],
  );
  const leftover = useMemo(
    () => unplacedClaims(segments, envelope.claims ?? []),
    [segments, envelope.claims],
  );
  const followUps = useMemo(() => buildFollowUps(envelope), [envelope]);

  // The run's SQL origin is stamped per run, so it is read once, here.
  const origin = envelope.queries?.[0]?.origin ?? null;
  const period = formatWindow(envelope.scope?.window ?? null);
  const sqlHeading = envelope.scope?.metric
    ? `${humanise(envelope.scope.metric)}${period ? ` · ${period}` : ''}`
    : null;

  // One running cue number, so a section that is not rendered does not leave a
  // gap in the choreography.
  let cue = 0;
  const next = () => cue++;

  const hasScope =
    !!envelope.scope?.metric ||
    !!envelope.scope?.window ||
    !!envelope.scope?.grain ||
    (envelope.scope?.filters?.length ?? 0) > 0 ||
    !!envelope.scope?.governed;

  return (
    <LineageProvider>
      <div className="space-y-block">
        {/* ── The conclusion. Everything else supports this, and it is the one
              element on the screen allowed to wear the accent edge. ──────── */}
        <Card
          tone="flat"
          className="edge-accent sheen px-6 py-7 sm:px-card sm:py-card"
          as="article"
        >
          <Reveal step={next()} reduced={reduced}>
            <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
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
                  starred={starred}
                  pinned={pinned}
                  canPin={canPin}
                  onToggleStar={onToggleStar ?? (() => {})}
                  onPin={onPin ?? (() => {})}
                  onInspect={onInspect ?? (() => {})}
                  onPresent={onPresent}
                />
              ) : null}
            </div>
          </Reveal>

          <Reveal step={next()} reduced={reduced}>
            {envelope.conclusion ? (
              <Conclusion
                conclusion={envelope.conclusion}
                claims={envelope.claims ?? []}
                className="mt-8"
              />
            ) : (
              <p className="mt-8 max-w-prose font-serif text-body-serif font-light text-ink-muted">
                This run produced no narrative conclusion.
              </p>
            )}
          </Reveal>

          <Reveal step={next()} reduced={reduced}>
            <Hairline className="my-8" />
            <RouteStrip route={envelope.route} status={envelope.status} />

            {hasScope && envelope.scope ? (
              <>
                <Hairline className="my-8" />
                <SectionLabel className="mb-4">Scope</SectionLabel>
                <ScopeLine scope={envelope.scope} />
              </>
            ) : null}
          </Reveal>
        </Card>

        {/* ── How this was computed. A first-class section, expanded. ───── */}
        {(envelope.queries?.length ?? 0) > 0 ? (
          <Reveal step={next()} reduced={reduced}>
            <QueryList
              queries={envelope.queries}
              claims={envelope.claims ?? []}
              origin={origin}
              {...(sqlHeading ? { heading: sqlHeading } : {})}
            />
            <div className="mt-4">
              <ReadOnlyNote />
            </div>
          </Reveal>
        ) : null}

        {/* ── Evidence. ─────────────────────────────────────────────────── */}
        {(envelope.evidence?.length ?? 0) > 0 ? (
          <Reveal step={next()} reduced={reduced}>
            <EvidenceSection envelope={envelope} theme={theme} />
          </Reveal>
        ) : null}

        {leftover.length > 0 ? (
          <Reveal step={next()} reduced={reduced}>
            <UnplacedClaims claims={leftover} />
          </Reveal>
        ) : null}

        {(envelope.caveats?.length ?? 0) > 0 || envelope.causal_boundary_note ? (
          <Reveal step={next()} reduced={reduced}>
            <CaveatCallout
              caveats={envelope.caveats ?? []}
              causalBoundaryNote={envelope.causal_boundary_note}
            />
          </Reveal>
        ) : null}

        {(envelope.next_actions?.length ?? 0) > 0 ? (
          <Reveal step={next()} reduced={reduced}>
            <NextActions actions={envelope.next_actions} />
          </Reveal>
        ) : null}

        {/* ── Trust, then what to ask next. ─────────────────────────────── */}
        <Reveal step={next()} reduced={reduced}>
          <TrustPanel envelope={envelope} />
        </Reveal>

        {!presenting && followUps.length > 0 ? (
          <Reveal step={next()} reduced={reduced}>
            <FollowUps followUps={followUps} onAsk={onAsk} />
          </Reveal>
        ) : null}

        <Reveal step={next()} reduced={reduced}>
          <RunMetricsFooter
            metrics={envelope.run_metrics}
            method={envelope.method}
            provenance={envelope.provenance}
            contractVersion={envelope.contract_version}
          />
        </Reveal>
      </div>
    </LineageProvider>
  );
}
