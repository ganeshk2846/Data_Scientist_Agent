import { RefreshCw } from 'lucide-react';
import { useRef, useState } from 'react';

import { PinTile } from './PinTile';
import { EmptyState } from '@/components/ui/EmptyState';
import { SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import type { PinsController } from '@/hooks/usePins';

/**
 * The pinboard.
 *
 * A grid of the figures the reader chose to keep, each one a value an envelope
 * stated and a timestamp saying when. Refresh re-asks; nothing is recomputed
 * here. The board is stored in this browser and labels itself as such.
 */
export function Pinboard({
  pins,
  onAsk,
  onEmptyAction,
}: {
  pins: PinsController;
  onAsk: (question: string) => void;
  /** Rendered in the empty state — the way back to the ask box. */
  onEmptyAction: () => void;
}) {
  const [dragging, setDragging] = useState<string | null>(null);
  /** The index the dragged tile is currently hovering, for a live reorder. */
  const over = useRef<number | null>(null);

  if (pins.pins.length === 0) {
    return (
      <section data-tour="pinboard">
        <header>
          <SectionLabel>Pinboard</SectionLabel>
          <h1 className="opsz-display mt-3 font-serif text-[2rem] leading-[1.12] tracking-[-0.02em] text-ink">
            Nothing pinned yet
          </h1>
        </header>
        <EmptyState
          art="pinboard"
          title="Keep the figures you watch"
          body="Pin a briefing's headline figure and it becomes a tile here. Refresh re-asks the question live and the new value counts in."
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

  const running = pins.pins.some((pin) => pins.state(pin.pinId) === 'running');

  return (
    <section data-tour="pinboard">
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div>
          <SectionLabel>Pinboard</SectionLabel>
          <h1 className="opsz-display mt-3 font-serif text-[2rem] leading-[1.12] tracking-[-0.02em] text-ink">
            {pins.pins.length} figure{pins.pins.length === 1 ? '' : 's'} on watch
          </h1>
          <p className="mt-2.5 max-w-prose text-[0.8125rem] leading-6 text-ink-faint">
            Each tile holds the value its run reported, with the time it was
            taken. Stored in this browser only.
          </p>
        </div>

        <button
          type="button"
          onClick={pins.refreshAll}
          disabled={running}
          className={cx(
            'inline-flex items-center gap-2 rounded-sm border border-hairline bg-surface px-3.5 py-2',
            'text-[0.8125rem] text-ink-muted transition-colors duration-hover ease-editorial',
            'hover:border-accent hover:text-ink disabled:cursor-not-allowed disabled:opacity-45',
          )}
        >
          <RefreshCw
            size={14}
            strokeWidth={1.5}
            aria-hidden
            className={running ? 'animate-spin' : ''}
          />
          {running ? 'Refreshing' : 'Refresh all'}
        </button>
      </header>

      <ul className="mt-group grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {pins.pins.map((pin, index) => (
          <PinTile
            key={pin.pinId}
            pin={pin}
            index={index}
            total={pins.pins.length}
            state={pins.state(pin.pinId)}
            justMeasured={pins.justMeasured(pin.pinId)}
            dragging={dragging === pin.pinId}
            onRefresh={() => pins.refresh(pin.pinId)}
            onRemove={() => pins.remove(pin.pinId)}
            onOpen={() => onAsk(pin.question)}
            onMoveBy={(delta) => pins.move(index, index + delta)}
            onDragStart={() => {
              setDragging(pin.pinId);
              over.current = index;
            }}
            onDragEnter={() => {
              if (over.current === null || over.current === index) return;
              pins.move(over.current, index);
              over.current = index;
            }}
            onDragEnd={() => {
              setDragging(null);
              over.current = null;
            }}
          />
        ))}
      </ul>
    </section>
  );
}
