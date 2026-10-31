import { ArrowUpRight } from 'lucide-react';
import { useState } from 'react';

import { NextActions } from './BriefingParts';
import { FitQuality } from './FitQuality';
import { Tag } from './StatusBadge';
import { VizCard } from '@/components/viz/VizCard';
import { Card, Hairline, SectionLabel } from '@/components/ui/Card';
import { asAnalystOutput, asDriverResult } from '@/lib/evidence';
import { formatSigned, humanise } from '@/lib/format';
import type { ResolvedTheme } from '@/lib/theme';
import {
  LAYOUT_LABEL,
  exampleQuestions,
  isComponentSpec,
  type AnswerLayout,
} from '@/lib/v2';
import type { AnswerEnvelopeV2, VisualizationSpec } from '@/types/v2';
import type { AnswerEnvelope } from '@/types/envelope';

/** Which intent layout a chart belongs to, read from what the spec draws. */
export function layoutOfSpec(spec: VisualizationSpec): AnswerLayout | null {
  const source = spec.source_artifact_id ?? '';
  if (source.includes(':python.driver#')) return 'why';
  if (source.includes(':python.forecast#') || spec.kind === 'forecast_fan') return 'forecast';
  if (source.includes(':python.scenario#')) return 'whatif';
  if (source.includes(':python.impact#')) return 'impact';
  if (source.includes(':python.segment#')) return 'nowwhat';
  return null;
}

interface PanelProps {
  layout: AnswerLayout;
  envelope: AnswerEnvelopeV2;
  specs: readonly VisualizationSpec[];
  theme: ResolvedTheme;
  onAsk: (question: string) => void;
}

/**
 * The answer layout for one intent (Track 5, item 6). Each reads only what
 * the envelope states: ranked drivers in the engine's own order, the
 * backend's charts, its assumptions and actions, the catalog's sentences.
 */
export function IntentPanel({ layout, envelope, specs, theme, onAsk }: PanelProps) {
  const asEnvelope = envelope as unknown as AnswerEnvelope;
  const charts = specs.filter((spec) => !isComponentSpec(spec));
  const components = specs.filter(isComponentSpec);

  return (
    <section data-print="flow" data-layout={layout} data-testid={`layout-${layout}`}>
      <div className="flex items-center gap-3">
        <SectionLabel>{LAYOUT_LABEL[layout]}</SectionLabel>
        <span aria-hidden className="h-px flex-1 bg-hairline" />
      </div>
      <div className="mt-group space-y-5">
        {layout === 'why' ? <WhyDrivers envelope={asEnvelope} /> : null}
        {charts.map((spec) => (
          <VizCard key={spec.viz_id} spec={spec} envelope={asEnvelope} theme={theme} />
        ))}
        {layout === 'why' && envelope.causal_boundary_note ? (
          <Card tone="sunken" className="px-5 py-4 sm:px-7">
            <SectionLabel>Causal boundary</SectionLabel>
            <p className="mt-2 max-w-prose text-small leading-relaxed text-ink-muted">
              {envelope.causal_boundary_note}
            </p>
          </Card>
        ) : null}
        {layout === 'forecast' ? (
          <Card tone="flat" className="edge-light px-5 py-5 sm:px-7">
            <FitQuality envelope={asEnvelope} />
            {components.length > 0 ? (
              <ComponentsToggle specs={components} envelope={asEnvelope} theme={theme} />
            ) : null}
          </Card>
        ) : null}
        {layout === 'whatif' ? <ScenarioAssumptions envelope={asEnvelope} /> : null}
        {layout === 'nowwhat' ? <NextActions actions={envelope.next_actions} /> : null}
        {layout === 'discovery' ? <Discovery envelope={envelope} onAsk={onAsk} /> : null}
      </div>
    </section>
  );
}

/** The engine's drivers in the order it ranked them; we do not re-sort. */
function WhyDrivers({ envelope }: { envelope: AnswerEnvelope }) {
  const driver = envelope.evidence.map(asDriverResult).find((result) => result !== null);
  if (!driver || driver.drivers.length === 0) return null;
  return (
    <Card tone="flat" className="edge-light px-5 py-5 sm:px-7">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <SectionLabel>Ranked drivers</SectionLabel>
        <span className="text-[0.6875rem] text-ink-faint">
          {driver.comparison_period} → {driver.current_period}
        </span>
      </div>
      <ol className="mt-4 divide-y divide-hairline" data-testid="ranked-drivers">
        {driver.drivers.map((item, index) => (
          <li key={`${item.dimension}-${item.value}`} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2.5">
            <span className="w-6 font-mono text-[0.6875rem] tabular-nums text-ink-faint">
              {String(index + 1).padStart(2, '0')}
            </span>
            <span className="min-w-0 flex-1 text-small text-ink">
              {humanise(item.value)}
              <span className="ml-2 text-[0.75rem] text-ink-faint">{humanise(item.dimension)}</span>
            </span>
            <span
              className={
                item.contribution < 0
                  ? 'text-small tabular-nums text-terracotta'
                  : 'text-small tabular-nums text-sage-ink'
              }
            >
              {formatSigned(item.contribution)}
            </span>
            <Tag>grade {item.grade}</Tag>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** Trend and seasonality, on request (Track 5, item 9). */
function ComponentsToggle({
  specs,
  envelope,
  theme,
}: {
  specs: readonly VisualizationSpec[];
  envelope: AnswerEnvelope;
  theme: ResolvedTheme;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Hairline className="my-5" />
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-2 rounded-sm border border-hairline px-3 py-1.5 text-[0.75rem] text-ink-muted transition-colors duration-hover ease-editorial hover:border-hairline-strong hover:text-ink"
        data-print="hide"
      >
        {open ? 'Hide' : 'Show'} trend and seasonality components
      </button>
      {open ? (
        <div className="mt-5 space-y-5">
          {specs.map((spec) => (
            <VizCard key={spec.viz_id} spec={spec} envelope={envelope} theme={theme} />
          ))}
        </div>
      ) : null}
    </>
  );
}

/** The scenario engine's stated assumptions and mandatory disclosures. */
function ScenarioAssumptions({ envelope }: { envelope: AnswerEnvelope }) {
  const items: string[] = [];
  for (const block of envelope.evidence) {
    const analyst = asAnalystOutput(block);
    if (!analyst || (analyst.module as string) !== 'scenario') continue;
    items.push(...analyst.assumptions);
    const result = analyst.result as Record<string, unknown> | null;
    const disclosures = result?.['disclosures'];
    if (Array.isArray(disclosures)) {
      items.push(...disclosures.filter((item): item is string => typeof item === 'string'));
    }
  }
  const unique = items.filter((item, index) => items.indexOf(item) === index);
  if (unique.length === 0) return null;
  return (
    <Card tone="sunken" className="px-5 py-5 sm:px-7">
      <SectionLabel>Scenario assumptions</SectionLabel>
      <ul className="mt-3 space-y-2" data-testid="scenario-assumptions">
        {unique.map((item) => (
          <li
            key={item}
            className="max-w-prose text-[0.8125rem] leading-relaxed text-ink-muted before:mr-2 before:text-ink-faint before:content-['—']"
          >
            {item}
          </li>
        ))}
      </ul>
    </Card>
  );
}

/**
 * Discovery: the catalog's own statements — tables, metrics, row counts and
 * date ranges — one per line, then the example questions it suggested.
 */
function Discovery({ envelope, onAsk }: { envelope: AnswerEnvelopeV2; onAsk: (question: string) => void }) {
  const examples = exampleQuestions(envelope.conclusion);
  return (
    <Card tone="flat" className="edge-light px-5 py-5 sm:px-7">
      <SectionLabel>What is in the warehouse</SectionLabel>
      <ul className="mt-3 divide-y divide-hairline" data-testid="discovery-facts">
        {envelope.claims.map((claim) => (
          <li key={claim.claim_id} className="flex gap-4 py-2 text-[0.8125rem] leading-relaxed text-ink-muted">
            <span className="w-8 shrink-0 font-mono text-[0.6875rem] text-ink-faint">{claim.claim_id}</span>
            <span className="min-w-0">{claim.text.replace(/\s*Try:\s*[“"][^”"]+[”"]/g, '')}</span>
          </li>
        ))}
      </ul>
      {examples.length > 0 ? (
        <>
          <Hairline className="my-5" />
          <SectionLabel>Example questions</SectionLabel>
          <ul className="mt-3 flex flex-wrap gap-2" data-print="hide">
            {examples.map((question) => (
              <li key={question}>
                <button
                  type="button"
                  onClick={() => onAsk(question)}
                  className="inline-flex items-center gap-1.5 rounded-sm border border-hairline px-3 py-1.5 text-[0.8125rem] text-ink-muted transition-colors duration-micro ease-editorial hover:border-hairline-strong hover:text-ink"
                >
                  {question}
                  <ArrowUpRight size={12} strokeWidth={1.5} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Card>
  );
}
