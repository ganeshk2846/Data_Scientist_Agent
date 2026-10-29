import { Braces, Check, Clipboard } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';

import { Hairline, SectionLabel } from '@/components/ui/Card';
import { Drawer } from '@/components/ui/Drawer';
import { Tag } from '@/components/briefing/StatusBadge';
import { useToast } from '@/components/ui/Toast';
import { cx } from '@/lib/cx';
import { formatDuration, formatNumber } from '@/lib/format';
import type { StageProgress } from '@/lib/stages';
import type { AnswerEnvelope } from '@/types/envelope';

/**
 * The run inspector.
 *
 * A waterfall of the pipeline, built from the SSE events and nothing else:
 * every duration is a `step_finished.duration_ms`, every summary is a
 * `step_finished.summary`, every start is a `step_started.at`. The bars' widths
 * and offsets are *layout* derived from those timestamps — the inspector draws
 * the run to scale, and prints only the figures the backend itself reported.
 *
 * It deliberately shows no total of its own. A sum of stage durations is a
 * number we would have computed; the envelope already carries the run's real
 * wall-clock latency in `run_metrics.latency_ms`, so that is what is printed.
 */

interface Lane {
  stage: StageProgress;
  /** Fraction of the lane the bar starts at, 0–1. Layout, not a figure. */
  offset: number;
  /** Fraction of the lane the bar spans, 0–1. */
  span: number;
}

/**
 * Lays the stages out to scale.
 *
 * When every stage carried a `step_started.at` the layout uses those real
 * timestamps, so a gap between two stages shows as a gap. When a timestamp is
 * missing — a reconnect that replayed only `step_finished`, say — the stages
 * fall back to butting up against one another in order, which is honest about
 * sequence without inventing a start time.
 */
function lanes(stages: readonly StageProgress[]): readonly Lane[] {
  const ran = stages.filter(
    (stage) => stage.state === 'ok' || stage.state === 'failed' || stage.state === 'running',
  );
  if (ran.length === 0) return [];

  const starts = ran.map((stage) =>
    stage.startedAt ? Date.parse(stage.startedAt) : Number.NaN,
  );
  const haveAll = starts.every((value) => Number.isFinite(value));

  if (haveAll) {
    const base = Math.min(...starts);
    const end = Math.max(
      ...ran.map((stage, index) => (starts[index] ?? base) + (stage.durationMs ?? 0)),
    );
    const total = Math.max(1, end - base);
    return ran.map((stage, index) => ({
      stage,
      offset: ((starts[index] ?? base) - base) / total,
      span: Math.max(0.012, (stage.durationMs ?? 0) / total),
    }));
  }

  const total = Math.max(
    1,
    ran.reduce((sum, stage) => sum + (stage.durationMs ?? 0), 0),
  );
  let cursor = 0;
  return ran.map((stage) => {
    const offset = cursor / total;
    cursor += stage.durationMs ?? 0;
    return { stage, offset, span: Math.max(0.012, (stage.durationMs ?? 0) / total) };
  });
}

const BAR: Record<StageProgress['state'], string> = {
  ok: 'bg-ink-faint',
  failed: 'bg-terracotta',
  running: 'bg-accent',
  pending: 'bg-hairline-strong',
  skipped: 'bg-hairline-strong',
};

export function RunInspector({
  open,
  onClose,
  stages,
  envelope,
  runId,
}: {
  open: boolean;
  onClose: () => void;
  stages: readonly StageProgress[];
  envelope: AnswerEnvelope | null;
  runId: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const toast = useToast();

  const rows = useMemo(() => lanes(stages), [stages]);
  const skipped = stages.filter((stage) => stage.state === 'skipped');
  const json = useMemo(
    () => (envelope ? JSON.stringify(envelope, null, 2) : ''),
    [envelope],
  );

  const copy = useCallback(() => {
    if (!json) return;
    void navigator.clipboard.writeText(json).then(
      () => {
        setCopied(true);
        toast.done('Answer envelope copied', `${formatNumber(json.length)} characters`);
        window.setTimeout(() => setCopied(false), 2_000);
      },
      () => toast.fault('The clipboard refused the copy.'),
    );
  }, [json, toast]);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Run inspector"
      lede="Every stage, to scale, from the run's own event stream."
    >
      {/* ── What the run itself reported ──────────────────────────────── */}
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3">
        <Figure label="Run" value={runId ? runId.slice(0, 12) : '—'} mono />
        {envelope ? (
          <>
            <Figure
              label="Latency"
              value={formatDuration(envelope.run_metrics.latency_ms)}
              mono
            />
            <Figure label="Queries" value={formatNumber(envelope.run_metrics.queries)} mono />
            <Figure label="Rows" value={formatNumber(envelope.run_metrics.rows)} mono />
            <Figure label="Tokens" value={formatNumber(envelope.run_metrics.tokens)} mono />
          </>
        ) : null}
      </div>
      <p className="mt-3 text-[0.6875rem] leading-4 text-ink-faint">
        Latency is the run's own wall clock from <code>run_metrics</code>. The
        inspector prints no total of its own.
      </p>

      <Hairline className="my-7" />

      {/* ── The waterfall ─────────────────────────────────────────────── */}
      <SectionLabel>Waterfall</SectionLabel>
      {rows.length === 0 ? (
        <p className="mt-4 text-[0.8125rem] leading-6 text-ink-faint">
          No stage events were captured for this run.
        </p>
      ) : (
        <ol className="mt-5 space-y-4">
          {rows.map(({ stage, offset, span }) => (
            <li key={stage.definition.step}>
              <div className="flex items-baseline justify-between gap-4">
                <span className="flex min-w-0 items-baseline gap-2.5">
                  <span className="font-mono text-[0.6875rem] tabular-nums text-ink-faint">
                    {stage.definition.step.padStart(2, '0')}
                  </span>
                  <span className="truncate text-[0.8125rem] leading-5 text-ink">
                    {stage.definition.label}
                  </span>
                </span>
                <span
                  className={cx(
                    'shrink-0 font-mono text-[0.75rem] tabular-nums',
                    stage.state === 'failed' ? 'text-terracotta' : 'text-ink-muted',
                  )}
                >
                  {stage.state === 'running'
                    ? 'running'
                    : formatDuration(stage.durationMs)}
                </span>
              </div>

              {/* The lane. One hairline track, one bar, drawn to scale. */}
              <div
                aria-hidden
                className="relative mt-2 h-1.5 w-full rounded-full bg-[rgb(var(--c-hairline)/0.8)]"
              >
                <span
                  className={cx(
                    'absolute inset-y-0 rounded-full transition-[left,width] duration-reveal ease-editorial',
                    BAR[stage.state],
                  )}
                  style={{
                    left: `${Math.min(99, offset * 100)}%`,
                    width: `${Math.min(100 - offset * 100, span * 100)}%`,
                  }}
                />
              </div>

              {stage.summary ? (
                <p className="mt-2 text-[0.75rem] leading-5 text-ink-faint">
                  {stage.summary}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      )}

      {skipped.length > 0 ? (
        <p className="mt-5 flex flex-wrap items-center gap-2 text-[0.6875rem] text-ink-faint">
          <span className="uppercase tracking-label">Not used on this route</span>
          {skipped.map((stage) => (
            <Tag key={stage.definition.step}>{stage.definition.label}</Tag>
          ))}
        </p>
      ) : null}

      <Hairline className="my-7" />

      {/* ── The contract, verbatim ────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Braces size={14} strokeWidth={1.5} aria-hidden className="text-ink-faint" />
          <SectionLabel>Answer envelope</SectionLabel>
        </div>
        {json ? (
          <button
            type="button"
            onClick={copy}
            className={cx(
              'inline-flex items-center gap-2 rounded-sm border px-2.5 py-1',
              'text-[0.75rem] transition-colors duration-hover ease-editorial',
              copied
                ? 'border-accent text-accent-ink'
                : 'border-hairline text-ink-muted hover:border-hairline-strong hover:text-ink',
            )}
          >
            <span className="relative grid h-3 w-3 place-items-center">
              <Clipboard
                size={11}
                strokeWidth={1.5}
                aria-hidden
                className={cx(
                  'absolute transition-all duration-200 ease-editorial',
                  copied ? 'scale-75 opacity-0' : 'scale-100 opacity-100',
                )}
              />
              <Check
                size={11}
                strokeWidth={1.5}
                aria-hidden
                className={cx(
                  'absolute transition-all duration-micro ease-editorial',
                  copied ? 'scale-100 opacity-100' : 'scale-50 opacity-0',
                )}
              />
            </span>
            {copied ? 'Copied' : 'Copy JSON'}
          </button>
        ) : null}
      </div>

      {json ? (
        <div
          tabIndex={0}
          role="region"
          aria-label="Raw answer envelope JSON"
          className="mt-3 max-h-[26rem] overflow-auto rounded-sm border border-hairline bg-sunken"
        >
          <pre className="p-4 font-mono text-[0.75rem] leading-5 text-ink-muted">
            {json}
          </pre>
        </div>
      ) : (
        <p className="mt-3 text-[0.8125rem] leading-6 text-ink-faint">
          The envelope has not been collected yet.
        </p>
      )}
    </Drawer>
  );
}

function Figure({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-micro uppercase tracking-label text-ink-faint">{label}</span>
      <span
        className={cx(
          'text-[0.8125rem] tabular-nums text-ink',
          mono && 'font-mono text-[0.75rem]',
        )}
      >
        {value}
      </span>
    </div>
  );
}
