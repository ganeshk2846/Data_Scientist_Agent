import { GripVertical, Loader2, RefreshCw, X } from 'lucide-react';

import { CountUp } from '@/components/ui/CountUp';
import { cx } from '@/lib/cx';
import { formatNumber, formatRelativeTime } from '@/lib/format';
import type { Pin } from '@/lib/pins';
import type { RefreshState } from '@/hooks/usePins';

/**
 * One KPI tile.
 *
 * The figure is the envelope's own value, stored at the moment it was measured.
 * Refresh re-asks the question and replaces it — see `hooks/usePins.ts`. The
 * tile therefore always says *when* its figure was taken, because a KPI with no
 * timestamp is the one thing worse than no KPI at all.
 *
 * Reordering is native HTML5 drag and drop, with a keyboard equivalent on the
 * handle: a drag-only affordance would put the feature out of reach for anyone
 * not using a pointer.
 */
export function PinTile({
  pin,
  index,
  total,
  state,
  justMeasured,
  dragging,
  onRefresh,
  onRemove,
  onOpen,
  onMoveBy,
  onDragStart,
  onDragEnter,
  onDragEnd,
}: {
  pin: Pin;
  index: number;
  total: number;
  state: RefreshState;
  justMeasured: boolean;
  dragging: boolean;
  onRefresh: () => void;
  onRemove: () => void;
  onOpen: () => void;
  onMoveBy: (delta: number) => void;
  onDragStart: () => void;
  onDragEnter: () => void;
  onDragEnd: () => void;
}) {
  const running = state === 'running';

  return (
    <li
      draggable
      onDragStart={onDragStart}
      onDragEnter={onDragEnter}
      onDragOver={(event) => event.preventDefault()}
      onDragEnd={onDragEnd}
      onDrop={(event) => {
        event.preventDefault();
        onDragEnd();
      }}
      className={cx(
        'group relative flex flex-col rounded-sm border bg-surface',
        'transition-[border-color,box-shadow,opacity] duration-micro ease-editorial',
        dragging
          ? 'border-accent opacity-60 shadow-lifted'
          : 'edge-light border-hairline shadow-soft hover:border-hairline-strong',
      )}
    >
      {/* ── The question, and the controls that only appear on approach ── */}
      <div className="flex items-start gap-2 px-4 pt-3.5">
        <button
          type="button"
          onClick={onOpen}
          className="min-w-0 flex-1 text-left"
          title="Ask this question again"
        >
          <span className="line-clamp-2 text-[0.8125rem] leading-5 text-ink-muted transition-colors duration-hover group-hover:text-ink">
            {pin.question}
          </span>
        </button>

        <span
          className={cx(
            'flex shrink-0 items-center gap-0.5 transition-opacity duration-hover ease-editorial',
            'opacity-0 focus-within:opacity-100 group-hover:opacity-100',
          )}
        >
          <button
            type="button"
            onClick={onRefresh}
            disabled={running}
            className="rounded-sm p-1 text-ink-faint transition-colors duration-hover hover:text-ink disabled:opacity-45"
          >
            {running ? (
              <Loader2 size={13} className="animate-spin" aria-hidden />
            ) : (
              <RefreshCw size={13} strokeWidth={1.5} aria-hidden />
            )}
            <span className="sr-only">Refresh this figure</span>
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="rounded-sm p-1 text-ink-faint transition-colors duration-hover hover:text-terracotta"
          >
            <X size={13} strokeWidth={1.5} aria-hidden />
            <span className="sr-only">Unpin</span>
          </button>
        </span>
      </div>

      {/* ── The figure ──────────────────────────────────────────────────── */}
      <div className="px-4 pb-3 pt-5">
        {/* `key` on the measured timestamp is what makes a refreshed value
            count in again: a new key is a new CountUp, from zero. */}
        <CountUp
          key={pin.measuredAt}
          value={pin.value}
          className={cx(
            'opsz-display block font-serif text-[2rem] leading-none tracking-[-0.018em]',
            'transition-colors duration-reveal ease-editorial',
            justMeasured ? 'text-accent-ink' : 'text-ink',
          )}
        />
        <div className="mt-2.5 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <span className="font-mono text-[0.6875rem] uppercase tracking-label text-ink-faint">
            {pin.unit}
          </span>
          {pin.period ? (
            <>
              <span aria-hidden className="h-2.5 w-px bg-hairline-strong" />
              <span className="text-[0.6875rem] text-ink-faint">{pin.period}</span>
            </>
          ) : null}
        </div>
      </div>

      {/* ── The footer rail: provenance, and the drag handle ───────────── */}
      <div className="mt-auto flex items-center gap-2 border-t border-hairline px-4 py-2">
        <span className="min-w-0 flex-1 truncate text-[0.6875rem] leading-4 text-ink-faint">
          {state === 'failed' ? (
            <span className="text-terracotta">
              Refresh returned no figure · showing{' '}
              {formatRelativeTime(pin.measuredAt)}
            </span>
          ) : running ? (
            'Re-asking…'
          ) : (
            `Measured ${formatRelativeTime(pin.measuredAt)}`
          )}
        </span>

        {/* The keyboard route through reordering. */}
        <span className="flex shrink-0 items-center">
          <button
            type="button"
            onClick={() => onMoveBy(-1)}
            disabled={index === 0}
            className="rounded-sm px-1 py-0.5 text-[0.6875rem] text-ink-faint transition-colors duration-hover hover:text-ink disabled:opacity-30"
          >
            <span aria-hidden>←</span>
            <span className="sr-only">Move earlier</span>
          </button>
          <button
            type="button"
            onClick={() => onMoveBy(1)}
            disabled={index === total - 1}
            className="rounded-sm px-1 py-0.5 text-[0.6875rem] text-ink-faint transition-colors duration-hover hover:text-ink disabled:opacity-30"
          >
            <span aria-hidden>→</span>
            <span className="sr-only">Move later</span>
          </button>
          <GripVertical
            size={13}
            strokeWidth={1.5}
            aria-hidden
            className="ml-0.5 cursor-grab text-ink-faint/70"
          />
        </span>
      </div>

      {/* The accessible reading of the tile, as one sentence. */}
      <span className="sr-only">
        {pin.question} — {formatNumber(pin.value)} {pin.unit}
        {pin.period ? `, ${pin.period}` : ''}, position {index + 1} of {total}.
      </span>
    </li>
  );
}
