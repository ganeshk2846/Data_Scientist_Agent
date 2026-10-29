import { motion } from 'framer-motion';
import { Check, ListTree, Loader2, Minus, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { StageNode } from './StageNode';
import { Card, SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import { formatDuration } from '@/lib/format';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import type { StageProgress } from '@/lib/stages';
import type { RunPhase } from '@/lib/runState';

interface PipelineTrackProps {
  stages: readonly StageProgress[];
  phase: RunPhase;
  reconnecting: boolean;
  /** Wall-clock start, so the timer measures the run and not the render. */
  startedAt: number | null;
}

const settled = (stage?: StageProgress) =>
  stage?.state === 'ok' || stage?.state === 'failed';

/**
 * The connector between two stages.
 *
 * When the left stage has finished and the right one has not, a point of accent
 * light travels the hairline — the signal visibly moving down the instrument.
 * Once both have finished the hairline is simply lit.
 */
function Connector({
  lit,
  travelling,
}: {
  lit: boolean;
  travelling: boolean;
}) {
  const reduced = useReducedMotion();

  return (
    <div aria-hidden className="relative mt-[0.59375rem] h-px flex-1 overflow-hidden bg-hairline">
      <motion.div
        className="absolute inset-y-0 left-0 bg-hairline-strong"
        initial={reduced ? { width: lit ? '100%' : 0 } : { width: 0 }}
        animate={{ width: lit ? '100%' : 0 }}
        transition={{ duration: reduced ? 0 : 0.6, ease: [0.22, 0.61, 0.36, 1] }}
      />
      {travelling && !reduced ? (
        <motion.div
          className="absolute inset-y-0 w-10"
          style={{
            background:
              'linear-gradient(90deg, transparent, rgb(var(--c-accent)) 55%, transparent)',
          }}
          initial={{ left: '-2.5rem' }}
          animate={{ left: '100%' }}
          transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
        />
      ) : null}
    </div>
  );
}

/** Counts up while the run is live. Reads the clock; computes no run data. */
function ElapsedTimer({ startedAt, running }: { startedAt: number | null; running: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  const frozen = useRef<number | null>(null);

  useEffect(() => {
    if (!running || startedAt === null) return;
    frozen.current = null;
    const timer = window.setInterval(() => setNow(Date.now()), 100);
    return () => window.clearInterval(timer);
  }, [running, startedAt]);

  if (startedAt === null) return null;
  if (!running && frozen.current === null) frozen.current = now;
  const elapsed = (running ? now : (frozen.current ?? now)) - startedAt;

  return (
    <span className="font-mono text-[0.75rem] tabular-nums text-ink-faint">
      {formatDuration(elapsed)}
    </span>
  );
}

export function PipelineTrack({
  stages,
  phase,
  reconnecting,
  startedAt,
}: PipelineTrackProps) {
  if (stages.length === 0) return null;

  const done = stages.filter(settled);
  const active = phase === 'submitting' || phase === 'streaming' || phase === 'fetching';

  return (
    <Card tone="flat" className="edge-light px-5 py-4 sm:px-6 sm:py-5" data-print="hide">
      <div className="flex flex-wrap items-baseline justify-between gap-x-5 gap-y-2">
        <div className="flex items-baseline gap-3">
          <SectionLabel>{active ? 'Running' : 'Pipeline'}</SectionLabel>
          <span className="font-mono text-[0.75rem] tabular-nums text-ink-faint">
            {done.length}/{stages.length}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {reconnecting ? (
            <span className="flex items-center gap-1.5 text-[0.6875rem] text-accent-ink">
              <Loader2 size={11} className="animate-spin" aria-hidden />
              reconnecting
            </span>
          ) : null}
          {phase === 'fetching' ? (
            <span className="text-[0.6875rem] text-ink-faint">collecting the answer…</span>
          ) : null}
          <ElapsedTimer startedAt={startedAt} running={active} />
        </div>
      </div>

      {/* Horizontal instrument track from `sm` up. */}
      <div role="list" aria-label="Pipeline stages" className="mt-5 hidden items-start sm:flex">
        {stages.map((stage, index) => {
          const next = stages[index + 1];
          return (
            <div key={stage.definition.step} role="listitem" className="flex min-w-0 flex-1">
              <StageNode stage={stage} orientation="horizontal" />
              {next ? (
                <Connector
                  lit={settled(stage) && settled(next)}
                  travelling={settled(stage) && !settled(next) && active}
                />
              ) : null}
            </div>
          );
        })}
      </div>

      {/* Stacked below `sm`, where seven nodes cannot read horizontally. */}
      <div role="list" aria-label="Pipeline stages" className="mt-4 space-y-3.5 sm:hidden">
        {stages.map((stage) => (
          <div key={stage.definition.step} role="listitem">
            <StageNode stage={stage} orientation="vertical" />
          </div>
        ))}
      </div>
    </Card>
  );
}

/**
 * Once the answer lands, the track compresses to a single slim bar: the run is
 * provenance now, not progress, so it should take a line and not a panel.
 */
export function PipelineSummaryBar({
  stages,
  onExpand,
  expanded,
  onInspect,
}: {
  stages: readonly StageProgress[];
  onExpand: () => void;
  expanded: boolean;
  /** Opens the run inspector — the full waterfall and the raw envelope. */
  onInspect: () => void;
}) {
  if (stages.length === 0) return null;

  const done = stages.filter(settled);
  const failed = stages.filter((stage) => stage.state === 'failed');
  const skipped = stages.filter((stage) => stage.state === 'skipped');
  const total = done.reduce((sum, stage) => sum + (stage.durationMs ?? 0), 0);

  return (
    <div
      data-print="hide"
      className={cx(
        'group flex w-full flex-wrap items-center gap-x-4 gap-y-2 rounded-sm border px-4 py-2.5',
        'border-hairline bg-[rgb(var(--c-surface)/0.6)] text-left',
        'transition-colors duration-hover ease-editorial hover:border-hairline-strong',
      )}
    >
      <span
        aria-hidden
        className={cx(
          'grid h-4 w-4 place-items-center rounded-full',
          failed.length > 0
            ? 'border border-terracotta text-terracotta'
            : 'border border-hairline-strong bg-surface text-ink-muted',
        )}
      >
        {failed.length > 0 ? (
          <X size={10} strokeWidth={1.5} aria-hidden />
        ) : (
          <Check size={10} strokeWidth={1.5} aria-hidden />
        )}
      </span>

      <span className="text-micro uppercase tracking-label text-ink">
        Pipeline · {done.length} stages
      </span>

      {/* A miniature of the track: one tick per stage. */}
      <span aria-hidden className="flex items-center gap-1">
        {stages.map((stage) => (
          <span
            key={stage.definition.step}
            className={cx(
              'h-2.5 w-px',
              stage.state === 'ok'
                ? 'bg-ink-faint'
                : stage.state === 'failed'
                  ? 'bg-terracotta'
                  : 'bg-hairline-strong',
            )}
          />
        ))}
      </span>

      {skipped.length > 0 ? (
        <span className="flex items-center gap-1 text-[0.6875rem] text-ink-faint">
          <Minus size={10} strokeWidth={1.5} aria-hidden />
          {skipped.length} not used
        </span>
      ) : null}

      {/* One time, labelled. Two bare durations side by side read as a bug. */}
      <span className="ml-auto flex items-center gap-3">
        <span className="text-micro uppercase tracking-label text-ink-faint">
          stage time
        </span>
        <span className="font-mono text-[0.75rem] tabular-nums text-ink-muted">
          {formatDuration(total)}
        </span>

        {/* Two destinations, so each is its own control: the track expands in
            place, the inspector opens the waterfall and the raw envelope. */}
        <button
          type="button"
          onClick={onExpand}
          aria-expanded={expanded}
          className="rounded-sm px-1.5 py-0.5 text-[0.6875rem] text-ink-faint transition-colors duration-hover ease-editorial hover:text-ink"
        >
          {expanded ? 'Hide track' : 'Show track'}
        </button>
        <button
          type="button"
          onClick={onInspect}
          title="Run inspector (I)"
          className="inline-flex items-center gap-1.5 rounded-sm border border-hairline px-2 py-0.5 text-[0.6875rem] text-ink-muted transition-colors duration-hover ease-editorial hover:border-hairline-strong hover:text-ink"
        >
          <ListTree size={11} strokeWidth={1.5} aria-hidden />
          Inspect
        </button>
      </span>
    </div>
  );
}
