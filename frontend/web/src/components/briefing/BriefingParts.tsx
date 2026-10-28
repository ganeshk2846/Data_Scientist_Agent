import { Info, ShieldAlert } from 'lucide-react';

import { ConfidenceGauge } from './ConfidenceGauge';
import { StatusBadge, Tag } from './StatusBadge';
import { Card, Hairline, SectionLabel } from '@/components/ui/Card';
import { Collapsible } from '@/components/ui/Collapsible';
import { cx } from '@/lib/cx';
import { formatDuration, formatNumber, formatWindow, humanise } from '@/lib/format';
import type {
  ActionOption,
  AnswerEnvelope,
  EnvelopeScope,
  MethodStep,
  Provenance,
  RouteSummary,
  RunMetrics,
  RunStatus,
} from '@/types/envelope';

/**
 * The route strip and gauge.
 *
 * Suppressed entirely for `status === 'error'`: `_error_envelope` stamps a
 * false `labels: ['blocked']` with confidence 0, and showing that would tell
 * the reader the guard blocked them when it did not.
 */
export function RouteStrip({
  route,
  status,
}: {
  route: RouteSummary;
  status: RunStatus;
}) {
  if (status === 'error') return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-5">
      <div className="min-w-0">
        <SectionLabel>Route</SectionLabel>
        <div className="mt-2.5 flex flex-wrap gap-2">
          {route.labels.map((label) => (
            <Tag key={label} tone="gold">
              {label}
            </Tag>
          ))}
        </div>
        <p className="mt-3 max-w-prose text-small leading-relaxed text-ink-faint">
          {route.reason}
        </p>
      </div>
      <ConfidenceGauge confidence={route.confidence} />
    </div>
  );
}

/** Scope as a quiet definition row. Only fields the backend actually set. */
export function ScopeLine({ scope }: { scope: EnvelopeScope }) {
  const items: readonly (readonly [string, string])[] = [
    ...(scope.metric ? ([['Metric', scope.metric]] as const) : []),
    ...(scope.window
      ? ([['Window', formatWindow(scope.window) ?? scope.window]] as const)
      : []),
    ...(scope.grain ? ([['Grain', humanise(scope.grain)]] as const) : []),
    ...(scope.filters.length > 0
      ? ([['Filters', scope.filters.join(', ')]] as const)
      : []),
    ...(scope.data_range ? ([['Data range', scope.data_range]] as const) : []),
  ];

  if (items.length === 0 && !scope.governed) return null;

  return (
    <dl className="flex flex-wrap gap-x-10 gap-y-4">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt className="text-micro uppercase text-ink-faint">{label}</dt>
          <dd className="mt-1 text-small tabular-nums text-ink">{value}</dd>
        </div>
      ))}
      {scope.governed ? (
        <div>
          <dt className="text-micro uppercase text-ink-faint">Governance</dt>
          <dd className="mt-1">
            <Tag tone="sage" title="Compiled from the governed metric registry">
              governed
            </Tag>
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

/** Caveats and the causal boundary note, in a quiet bordered callout. */
export function CaveatCallout({
  caveats,
  causalBoundaryNote,
}: {
  caveats: readonly string[];
  causalBoundaryNote: string | null;
}) {
  if (caveats.length === 0 && !causalBoundaryNote) return null;

  return (
    <Card tone="sunken" className="p-5 sm:p-6">
      {caveats.length > 0 ? (
        <div>
          <div className="flex items-center gap-2">
            <Info size={13} strokeWidth={1.75} aria-hidden className="text-ink-faint" />
            <SectionLabel>Caveats</SectionLabel>
          </div>
          <ul className="mt-3 space-y-2">
            {caveats.map((caveat) => (
              <li
                key={caveat}
                className="max-w-prose text-small leading-relaxed text-ink-muted"
              >
                {caveat}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {caveats.length > 0 && causalBoundaryNote ? <Hairline className="my-5" /> : null}

      {causalBoundaryNote ? (
        <div>
          <div className="flex items-center gap-2">
            <ShieldAlert
              size={13}
              strokeWidth={1.75}
              aria-hidden
              className="text-ink-faint"
            />
            <SectionLabel>Causal boundary</SectionLabel>
          </div>
          <p className="mt-3 max-w-prose text-small leading-relaxed text-ink-muted">
            {causalBoundaryNote}
          </p>
        </div>
      ) : null}
    </Card>
  );
}

/**
 * Ranked next actions.
 *
 * `build_answer_envelope` hardcodes `next_actions=()`, so against the live
 * backend this section never renders. It is built to contract so it works the
 * moment the backend populates it, and it is visible today in mock mode.
 * Nothing here is ever invented.
 */
export function NextActions({ actions }: { actions: readonly ActionOption[] }) {
  if (actions.length === 0) return null;
  const ranked = [...actions].sort((a, b) => a.rank - b.rank);

  return (
    <section>
      <SectionLabel>Next actions</SectionLabel>
      <div className="mt-4 space-y-3">
        {ranked.map((action) => (
          <Card key={action.action_id} className="px-5 py-4">
            <Collapsible
              summary={
                <span className="flex flex-wrap items-baseline gap-x-4 gap-y-1.5">
                  <span className="font-mono text-[0.6875rem] tabular-nums text-gold">
                    {String(action.rank).padStart(2, '0')}
                  </span>
                  <span className="min-w-0 flex-1 font-serif text-[1.0625rem] text-ink">
                    {action.title}
                  </span>
                  <Tag>{humanise(action.kind)}</Tag>
                </span>
              }
            >
              <div className="mt-4 space-y-5 pl-7">
                <ActionList title="Assumptions" items={action.assumptions} />
                <ActionList title="Trade-offs" items={action.trade_offs} />
                <ActionList title="What to monitor" items={action.monitor} />
                <ActionList
                  title="What would change the ranking"
                  items={action.data_that_would_change_ranking}
                />
                {action.sensitivity ? (
                  <div>
                    <SectionLabel>Sensitivity</SectionLabel>
                    <p className="mt-2 max-w-prose text-small leading-relaxed text-ink-muted">
                      {action.sensitivity}
                    </p>
                  </div>
                ) : null}
              </div>
            </Collapsible>
          </Card>
        ))}
      </div>
    </section>
  );
}

function ActionList({ title, items }: { title: string; items: readonly string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <SectionLabel>{title}</SectionLabel>
      <ul className="mt-2 space-y-1.5">
        {items.map((item) => (
          <li
            key={item}
            className="max-w-prose text-small leading-relaxed text-ink-muted before:mr-2 before:text-ink-faint before:content-['—']"
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The discreet footer strip: latency, queries, rows, tokens. */
export function RunMetricsFooter({
  metrics,
  method,
  provenance,
  contractVersion,
}: {
  metrics: RunMetrics;
  method: readonly MethodStep[];
  provenance: Provenance;
  contractVersion: string;
}) {
  const figures: readonly (readonly [string, string])[] = [
    ['Latency', formatDuration(metrics.latency_ms)],
    ['Queries', formatNumber(metrics.queries)],
    ['Rows', formatNumber(metrics.rows)],
    ['Tokens', formatNumber(metrics.tokens)],
    ...(metrics.retries > 0
      ? ([['Retries', formatNumber(metrics.retries)]] as const)
      : []),
  ];

  return (
    <footer className="border-t border-hairline pt-5">
      <dl className="flex flex-wrap gap-x-10 gap-y-3">
        {figures.map(([label, value]) => (
          <div key={label} className="flex items-baseline gap-2">
            <dt className="text-micro uppercase text-ink-faint">{label}</dt>
            <dd className="font-mono text-small tabular-nums text-ink-muted">{value}</dd>
          </div>
        ))}
      </dl>

      <p className="mt-4 font-mono text-[0.6875rem] leading-relaxed text-ink-faint">
        {method.length > 0 ? (
          <>method {method.map((step) => step.name).join(', ')} · </>
        ) : null}
        contract {contractVersion}
        {provenance.catalog_version ? (
          <> · catalog {provenance.catalog_version.slice(0, 12)}</>
        ) : null}
        {provenance.model_name && provenance.model_name !== 'none' ? (
          <> · model {provenance.model_name}</>
        ) : (
          <> · no model used</>
        )}
        {provenance.snapshot_id ? <> · {provenance.snapshot_id}</> : null}
        {provenance.commit ? <> · {provenance.commit.slice(0, 8)}</> : null}
      </p>
    </footer>
  );
}

/** The headline row above the narrative. */
export function BriefingHeader({
  envelope,
  className,
}: {
  envelope: AnswerEnvelope;
  className?: string;
}) {
  return (
    <div className={cx('flex flex-wrap items-center gap-3', className)}>
      <StatusBadge status={envelope.status} />
      <span className="font-mono text-[0.6875rem] text-ink-faint">
        {envelope.run_id.slice(0, 12)}
      </span>
    </div>
  );
}
