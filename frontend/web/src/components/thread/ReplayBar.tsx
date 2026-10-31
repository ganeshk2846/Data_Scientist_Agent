import { ChevronLeft, ChevronRight, X } from 'lucide-react';

/**
 * Stepping through a stored conversation, one answer at a time. Each step
 * reopens that turn's own stored envelope; nothing is re-asked.
 */
export function ReplayBar({
  index,
  total,
  onPrevious,
  onNext,
  onExit,
}: {
  index: number;
  total: number;
  onPrevious: () => void;
  onNext: () => void;
  onExit: () => void;
}) {
  const button =
    'inline-flex items-center gap-1 rounded-sm border border-hairline px-2.5 py-1 text-[0.75rem] text-ink-muted transition-colors duration-hover hover:border-hairline-strong hover:text-ink disabled:cursor-not-allowed disabled:opacity-50';
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-3 rounded-sm border border-hairline-strong bg-sunken px-4 py-2.5"
      data-print="hide"
      data-testid="replay-bar"
      role="region"
      aria-label="Conversation replay"
    >
      <span className="text-[0.8125rem] text-ink" aria-live="polite">
        Replaying · turn {index + 1} of {total}
      </span>
      <div className="flex gap-2">
        <button type="button" className={button} onClick={onPrevious} disabled={index === 0}>
          <ChevronLeft size={13} strokeWidth={1.5} aria-hidden />
          Previous turn
        </button>
        <button type="button" className={button} onClick={onNext} disabled={index >= total - 1}>
          Next turn
          <ChevronRight size={13} strokeWidth={1.5} aria-hidden />
        </button>
        <button type="button" className={button} onClick={onExit}>
          <X size={13} strokeWidth={1.5} aria-hidden />
          Exit replay
        </button>
      </div>
    </div>
  );
}
