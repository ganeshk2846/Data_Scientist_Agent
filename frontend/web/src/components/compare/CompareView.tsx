import { ArrowLeftRight, ChevronRight } from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { SqlBlock } from '@/components/queries/SqlBlock';
import { StatusBadge, Tag } from '@/components/briefing/StatusBadge';
import { EmptyState } from '@/components/ui/EmptyState';
import { Hairline, SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import { asAnomalyResult, asDriverResult, asLookup } from '@/lib/evidence';
import { asHeroFigure } from '@/lib/evidenceTitle';
import { formatDuration, formatNumber, formatPercent, formatWindow, humanise } from '@/lib/format';
import type { HistoryEntry } from '@/hooks/useSession';
import type { AnswerEnvelope } from '@/types/envelope';

/**
 * Compare mode.
 *
 * Two answers, side by side, aligned section by section. It shows **no
 * computed difference** — not a delta, not a ratio, not a "7% higher". Each
 * column prints only its own envelope's values, and the alignment is what lets
 * the reader do the comparing. That restraint is the feature: the moment the
 * interface subtracts two figures it has produced a number no claim backs, and
 * the whole trust model goes with it.
 */

interface Side {
  entry: HistoryEntry;
  envelope: AnswerEnvelope;
}

/** One aligned band: a label, then the same slot in each column. */
function Band({
  label,
  left,
  right,
  note,
}: {
  label: string;
  left: ReactNode;
  right: ReactNode;
  note?: string;
}) {
  return (
    <section className="pt-block first:pt-0">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <SectionLabel>{label}</SectionLabel>
        {note ? (
          <span className="text-[0.6875rem] leading-4 text-ink-faint">{note}</span>
        ) : null}
      </div>
      <div className="mt-4 grid gap-x-10 gap-y-6 lg:grid-cols-2">
        <div className="min-w-0">{left}</div>
        <div className="min-w-0 lg:border-l lg:border-hairline lg:pl-10">{right}</div>
      </div>
    </section>
  );
}

function Conclusion({ envelope }: { envelope: AnswerEnvelope }) {
  if (!envelope.conclusion) {
    return (
      <p className="text-[0.8125rem] leading-6 text-ink-faint">
        This run produced no narrative conclusion.
      </p>
    );
  }
  return (
    <p className="onum opsz-title max-w-prose font-serif text-[1.0625rem] font-light leading-7 text-ink">
      {envelope.conclusion}
    </p>
  );
}

function ScopeBlock({ envelope }: { envelope: AnswerEnvelope }) {
  const period = formatWindow(envelope.scope.window);
  const items: readonly (readonly [string, string])[] = [
    ...(envelope.scope.metric
      ? ([['Metric', humanise(envelope.scope.metric)]] as const)
      : []),
    ...(period ? ([['Period', period]] as const) : []),
    ...(envelope.scope.grain
      ? ([['Grain', humanise(envelope.scope.grain)]] as const)
      : []),
    ...(envelope.scope.filters.length > 0
      ? ([['Filters', envelope.scope.filters.join(', ')]] as const)
      : []),
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={envelope.status} />
        {envelope.route.labels.map((label) => (
          <Tag key={label}>{label}</Tag>
        ))}
        {envelope.scope.governed ? <Tag tone="sage">governed</Tag> : null}
      </div>
      {items.length > 0 ? (
        <dl className="flex flex-wrap gap-x-8 gap-y-3">
          {items.map(([label, value]) => (
            <div key={label}>
              <dt className="text-micro uppercase text-ink-faint">{label}</dt>
              <dd className="mt-1 text-[0.8125rem] tabular-nums text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

/**
 * Each evidence block, in its own voice — the figure for a single-cell lookup,
 * the verdict for an anomaly, the shape for a table. Every value is the
 * envelope's own, and the two columns are never put through one another.
 */
function EvidenceBlocks({ envelope }: { envelope: AnswerEnvelope }) {
  if (envelope.evidence.length === 0) {
    return (
      <p className="text-[0.8125rem] leading-6 text-ink-faint">
        This run recorded no evidence blocks.
      </p>
    );
  }

  return (
    <ul className="space-y-4">
      {envelope.evidence.map((block, index) => {
        const lookup = asLookup(block);
        const hero = lookup ? asHeroFigure(lookup) : null;
        const anomaly = asAnomalyResult(block);
        const driver = asDriverResult(block);

        return (
          <li
            key={`${block.module}-${index}`}
            className="edge-light rounded-sm border border-hairline bg-surface px-4 py-3.5 shadow-soft"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1.5">
              <span className="text-[0.8125rem] leading-5 text-ink">
                {humanise(block.module)}
              </span>
              <span className="font-mono text-[0.6875rem] text-ink-faint">
                {block.source_claims.join(', ') || '—'}
              </span>
            </div>

            {hero ? (
              <div className="mt-3">
                <span className="opsz-display block font-serif text-[1.75rem] leading-none tracking-[-0.016em] text-ink">
                  {formatNumber(hero.value)}
                </span>
                <span className="mt-2 block font-mono text-[0.6875rem] uppercase tracking-label text-ink-faint">
                  {hero.unit}
                </span>
              </div>
            ) : null}

            {anomaly ? (
              <dl className="mt-3 space-y-1.5">
                <Row label="Verdict" value={humanise(anomaly.verdict)} />
                <Row label="Actual" value={formatNumber(anomaly.actual)} />
                <Row label="Expected" value={formatNumber(anomaly.expected)} />
                <Row
                  label="Range"
                  value={`${formatNumber(anomaly.expected_range[0])} – ${formatNumber(
                    anomaly.expected_range[1],
                  )}`}
                />
                <Row
                  label="Deviation"
                  value={formatPercent(anomaly.deviation_pct, true)}
                />
                <Row label="Baseline" value={humanise(anomaly.baseline_kind)} />
              </dl>
            ) : null}

            {driver ? (
              <dl className="mt-3 space-y-1.5">
                <Row label="Metric" value={driver.metric} />
                <Row label="Total change" value={formatNumber(driver.total_change)} />
                <Row label="Drivers" value={formatNumber(driver.drivers.length)} />
              </dl>
            ) : null}

            {lookup && !hero ? (
              <dl className="mt-3 space-y-1.5">
                <Row label="Rows" value={lookup.row_count !== null ? formatNumber(lookup.row_count) : '—'} />
                <Row
                  label="Columns"
                  value={lookup.columns.map((column) => column.name).join(', ')}
                />
              </dl>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-3">
      <dt className="w-[5.5rem] shrink-0 text-micro uppercase tracking-label text-ink-faint">
        {label}
      </dt>
      <dd className="min-w-0 flex-1 text-[0.75rem] tabular-nums text-ink-muted">
        {value}
      </dd>
    </div>
  );
}

function Queries({ envelope }: { envelope: AnswerEnvelope }) {
  if (envelope.queries.length === 0) {
    return (
      <p className="text-[0.8125rem] leading-6 text-ink-faint">
        This run ran no SQL.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {envelope.queries.map((query) => (
        <div key={query.query_id}>
          <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-mono text-[0.75rem] text-ink">{query.query_id}</span>
            <Tag tone={query.status === 'ok' ? 'sage' : 'terracotta'}>{query.status}</Tag>
            <span className="font-mono text-[0.6875rem] tabular-nums text-ink-faint">
              {formatDuration(query.duration_ms)}
            </span>
          </div>
          <SqlBlock sql={query.sql} />
        </div>
      ))}
    </div>
  );
}

function Metrics({ envelope }: { envelope: AnswerEnvelope }) {
  const metrics = envelope.run_metrics;
  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-3">
      {(
        [
          ['Latency', formatDuration(metrics.latency_ms)],
          ['Queries', formatNumber(metrics.queries)],
          ['Rows', formatNumber(metrics.rows)],
          ['Tokens', formatNumber(metrics.tokens)],
        ] as const
      ).map(([label, value]) => (
        <div key={label} className="flex items-baseline gap-2">
          <dt className="text-micro uppercase text-ink-faint">{label}</dt>
          <dd className="font-mono text-[0.8125rem] tabular-nums text-ink-muted">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** The column header: whose answer this is. */
function Column({ side, position }: { side: Side; position: 'A' | 'B' }) {
  return (
    <div className="min-w-0">
      <div className="flex items-baseline gap-2.5">
        <span className="font-mono text-[0.6875rem] text-accent-ink">{position}</span>
        <span className="font-mono text-[0.6875rem] text-ink-faint">
          {side.envelope.run_id.slice(0, 12)}
        </span>
      </div>
      <h2 className="opsz-title mt-2 font-serif text-[1.125rem] leading-6 tracking-[-0.008em] text-ink">
        {side.entry.question}
      </h2>
    </div>
  );
}

export function CompareView({
  history,
  onEmptyAction,
}: {
  history: readonly HistoryEntry[];
  onEmptyAction: () => void;
}) {
  const answered = useMemo(
    () => history.filter((entry): entry is HistoryEntry => entry.envelope !== null),
    [history],
  );

  const [leftId, setLeftId] = useState<string | null>(null);
  const [rightId, setRightId] = useState<string | null>(null);

  // Default to the two most recent, which is what a reader almost always wants.
  useEffect(() => {
    if (answered.length < 2) return;
    setLeftId((current) => current ?? answered[0]?.localId ?? null);
    setRightId((current) => current ?? answered[1]?.localId ?? null);
  }, [answered]);

  const pick = (localId: string | null): Side | null => {
    const entry = answered.find((candidate) => candidate.localId === localId);
    if (!entry?.envelope) return null;
    return { entry, envelope: entry.envelope };
  };

  const left = pick(leftId);
  const right = pick(rightId);

  if (answered.length < 2) {
    return (
      <section>
        <header>
          <SectionLabel>Compare</SectionLabel>
          <h1 className="opsz-display mt-3 font-serif text-[2rem] leading-[1.12] tracking-[-0.02em] text-ink">
            Two answers, aligned
          </h1>
        </header>
        <EmptyState
          art="compare"
          title="Ask a second question"
          body="Compare puts two past answers side by side, section by section — conclusion against conclusion, evidence against evidence, SQL against SQL. It needs two stored answers to work with."
          action={
            <button
              type="button"
              onClick={onEmptyAction}
              className="inline-flex items-center gap-2 rounded-sm border border-hairline-strong bg-surface px-4 py-2 text-[0.8125rem] text-ink transition-colors duration-hover ease-editorial hover:border-accent"
            >
              Ask a question
            </button>
          }
        />
      </section>
    );
  }

  return (
    <section>
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-5">
        <div>
          <SectionLabel>Compare</SectionLabel>
          <h1 className="opsz-display mt-3 font-serif text-[2rem] leading-[1.12] tracking-[-0.02em] text-ink">
            Two answers, aligned
          </h1>
          <p className="mt-2.5 max-w-prose text-[0.8125rem] leading-6 text-ink-faint">
            Each column shows only its own run's values. No difference is
            calculated here — the alignment is the comparison.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <Picker
            label="A"
            value={leftId}
            entries={answered}
            onChange={setLeftId}
            exclude={rightId}
          />
          <button
            type="button"
            onClick={() => {
              setLeftId(rightId);
              setRightId(leftId);
            }}
            title="Swap the columns"
            className="mb-0.5 rounded-sm border border-hairline bg-surface p-2 text-ink-faint transition-colors duration-hover ease-editorial hover:border-hairline-strong hover:text-ink"
          >
            <ArrowLeftRight size={14} strokeWidth={1.5} aria-hidden />
            <span className="sr-only">Swap the columns</span>
          </button>
          <Picker
            label="B"
            value={rightId}
            entries={answered}
            onChange={setRightId}
            exclude={leftId}
          />
        </div>
      </header>

      <Hairline className="mt-group" />

      {left && right ? (
        <div className="mt-group">
          {/* The two headers sit on the same grid as every band below. */}
          <div className="grid gap-x-10 gap-y-6 lg:grid-cols-2">
            <Column side={left} position="A" />
            <div className="lg:border-l lg:border-hairline lg:pl-10">
              <Column side={right} position="B" />
            </div>
          </div>

          <div className="mt-block space-y-0 divide-y divide-hairline">
            <Band
              label="Scope and route"
              left={<ScopeBlock envelope={left.envelope} />}
              right={<ScopeBlock envelope={right.envelope} />}
            />
            <Band
              label="Conclusion"
              left={<Conclusion envelope={left.envelope} />}
              right={<Conclusion envelope={right.envelope} />}
            />
            <Band
              label="Evidence"
              note="each run's own blocks, in its own units"
              left={<EvidenceBlocks envelope={left.envelope} />}
              right={<EvidenceBlocks envelope={right.envelope} />}
            />
            <Band
              label="How it was computed"
              left={<Queries envelope={left.envelope} />}
              right={<Queries envelope={right.envelope} />}
            />
            <Band
              label="Run"
              left={<Metrics envelope={left.envelope} />}
              right={<Metrics envelope={right.envelope} />}
            />
          </div>
        </div>
      ) : (
        <p className="mt-group text-[0.8125rem] leading-6 text-ink-faint">
          Choose two answers above.
        </p>
      )}
    </section>
  );
}

function Picker({
  label,
  value,
  entries,
  onChange,
  exclude,
}: {
  label: string;
  value: string | null;
  entries: readonly HistoryEntry[];
  onChange: (localId: string) => void;
  exclude: string | null;
}) {
  return (
    <label className="block">
      <span className="block text-micro uppercase tracking-label text-ink-faint">
        {label}
      </span>
      <span className="relative mt-1.5 inline-flex">
        <select
          value={value ?? ''}
          onChange={(event) => onChange(event.target.value)}
          className={cx(
            'w-[min(18rem,calc(100vw-6rem))] appearance-none rounded-sm border border-hairline bg-sunken',
            'py-1.5 pl-3 pr-9 text-[0.8125rem] leading-5 text-ink',
            'transition-colors duration-hover ease-editorial hover:border-hairline-strong',
          )}
        >
          {entries.map((entry) => (
            <option
              key={entry.localId}
              value={entry.localId}
              disabled={entry.localId === exclude}
            >
              {entry.question}
            </option>
          ))}
        </select>
        <ChevronRight
          size={13}
          strokeWidth={1.5}
          aria-hidden
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rotate-90 text-ink-faint"
        />
      </span>
    </label>
  );
}
