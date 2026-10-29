import { motion } from 'framer-motion';
import { Check, Minus, X } from 'lucide-react';

import { cx } from '@/lib/cx';
import { formatDuration } from '@/lib/format';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import type { StageProgress } from '@/lib/stages';

/**
 * The marker is small, and deliberately quiet once it has done its job: a
 * finished stage is struck in ink, and only the stage that is *running* wears
 * the accent. On a live track that leaves exactly one accented element moving
 * down the instrument, which is the whole point of the device.
 */
function Marker({ state }: { state: StageProgress['state'] }) {
  const reduced = useReducedMotion();

  if (state === 'ok') {
    return (
      <span className="grid h-6 w-6 place-items-center rounded-full border border-hairline-strong bg-surface text-ink-muted">
        <Check size={11} strokeWidth={1.5} aria-hidden />
      </span>
    );
  }
  if (state === 'failed') {
    return (
      <span className="grid h-6 w-6 place-items-center rounded-full border border-terracotta bg-terracotta-wash text-terracotta">
        <X size={12} strokeWidth={1.5} aria-hidden />
      </span>
    );
  }
  if (state === 'skipped') {
    return (
      <span className="grid h-6 w-6 place-items-center rounded-full border border-dashed border-hairline-strong text-ink-faint">
        <Minus size={11} strokeWidth={1.5} aria-hidden />
      </span>
    );
  }
  if (state === 'running') {
    return (
      <span className="relative grid h-6 w-6 place-items-center rounded-full border border-accent bg-[var(--c-accent-wash)]">
        {/* A slow breathing dot, not a spinner — calm, not busy. */}
        <motion.span
          className="h-2 w-2 rounded-full bg-accent"
          animate={reduced ? {} : { opacity: [1, 0.35, 1], scale: [1, 0.82, 1] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
        />
      </span>
    );
  }
  return (
    <span className="grid h-6 w-6 place-items-center rounded-full border border-hairline">
      <span className="h-1.5 w-1.5 rounded-full bg-hairline-strong" />
    </span>
  );
}

interface StageNodeProps {
  stage: StageProgress;
  /** Horizontal on the track, stacked on narrow screens. */
  orientation: 'horizontal' | 'vertical';
}

export function StageNode({ stage, orientation }: StageNodeProps) {
  const { definition, state, durationMs, summary } = stage;
  const dim = state === 'pending' || state === 'skipped';
  const horizontal = orientation === 'horizontal';

  const detail = summary ?? definition.blurb;
  const stateWord =
    state === 'ok'
      ? 'finished'
      : state === 'failed'
        ? 'failed'
        : state === 'running'
          ? 'running'
          : state === 'skipped'
            ? 'not used on this route'
            : 'waiting';

  return (
    <div
      className={cx(
        'group/stage relative flex min-w-0',
        horizontal ? 'flex-1 flex-col items-center text-center' : 'items-start gap-3',
      )}
    >
      <Marker state={state} />

      <div className={cx(horizontal ? 'mt-2.5 w-full px-1' : 'min-w-0 flex-1 pt-0.5')}>
        <div
          className={cx(
            'truncate text-small transition-colors duration-micro',
            dim ? 'text-ink-faint' : 'text-ink',
          )}
        >
          {definition.label}
        </div>
        <div className="mt-0.5 h-4 font-mono text-[0.6875rem] tabular-nums text-ink-faint">
          {state === 'ok' || state === 'failed' ? formatDuration(durationMs) : null}
          {state === 'skipped' ? 'not used' : null}
          {state === 'running' ? 'running' : null}
        </div>

        {/* Stacked layout has room for the summary inline. */}
        {!horizontal && (state === 'ok' || state === 'failed') && summary ? (
          <p className="mt-1 text-[0.6875rem] leading-relaxed text-ink-faint">{summary}</p>
        ) : null}
      </div>

      {/* The horizontal track keeps summaries in a hover/focus tooltip. */}
      {horizontal ? (
        <div
          role="tooltip"
          className={cx(
            'pointer-events-none absolute bottom-full left-1/2 z-20 mb-3 w-56 -translate-x-1/2',
            'rounded-sm border border-hairline bg-raised p-3 text-left shadow-overlay',
            'opacity-0 transition-opacity duration-micro ease-editorial',
            'group-hover/stage:opacity-100 group-focus-within/stage:opacity-100',
          )}
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-small text-ink">{definition.label}</span>
            <span className="font-mono text-[0.6875rem] tabular-nums text-ink-faint">
              step {definition.step}
            </span>
          </div>
          <p className="mt-1.5 text-[0.6875rem] leading-relaxed text-ink-muted">{detail}</p>
        </div>
      ) : null}

      <span className="sr-only">
        {definition.label}: {stateWord}
        {durationMs != null ? `, ${formatDuration(durationMs)}` : ''}
      </span>
    </div>
  );
}
