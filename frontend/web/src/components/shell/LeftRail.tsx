import { Plus, X } from 'lucide-react';

import { HistoryItem } from './HistoryItem';
import { Hairline, SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import type { HistoryEntry } from '@/hooks/useSession';

interface LeftRailProps {
  history: readonly HistoryEntry[];
  activeId: string | null;
  open: boolean;
  onSelect: (localId: string) => void;
  onNewQuestion: () => void;
  onClose: () => void;
}

export function LeftRail({
  history,
  activeId,
  open,
  onSelect,
  onNewQuestion,
  onClose,
}: LeftRailProps) {
  return (
    <>
      {/* Mobile scrim. Glass blur is reserved for overlays like this one. */}
      <div
        aria-hidden
        onClick={onClose}
        className={cx(
          'fixed inset-0 z-30 bg-[rgb(var(--c-bg)/0.55)] backdrop-blur-sm lg:hidden',
          'transition-opacity duration-micro ease-editorial',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      />

      <aside
        aria-label="This session"
        className={cx(
          'fixed inset-y-0 left-0 z-40 flex w-rail flex-col border-r border-hairline bg-sunken',
          'transition-transform duration-reveal ease-editorial',
          'lg:sticky lg:top-16 lg:z-0 lg:h-[calc(100vh-4rem)] lg:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 shrink-0 items-center gap-2 px-4 lg:h-14">
          <SectionLabel className="flex-1">This session</SectionLabel>
          <button
            type="button"
            onClick={onNewQuestion}
            aria-label="Ask a new question"
            title="Ask a new question"
            className="rounded-sm p-1.5 text-ink-faint transition-colors duration-micro hover:text-gold"
          >
            <Plus size={15} strokeWidth={1.75} aria-hidden />
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close history"
            className="rounded-sm p-1.5 text-ink-faint transition-colors duration-micro hover:text-ink lg:hidden"
          >
            <X size={15} strokeWidth={1.75} aria-hidden />
          </button>
        </div>

        <Hairline />

        <nav className="min-h-0 flex-1 overflow-y-auto px-2.5 py-3">
          {history.length === 0 ? (
            <p className="px-3 py-6 text-small leading-relaxed text-ink-faint">
              Questions you ask will collect here. Select one to reopen its briefing.
            </p>
          ) : (
            <ul className="space-y-0.5">
              {history.map((entry) => (
                <HistoryItem
                  key={entry.localId}
                  entry={entry}
                  active={entry.localId === activeId}
                  onSelect={onSelect}
                />
              ))}
            </ul>
          )}
        </nav>

        <Hairline />

        <div className="shrink-0 px-4 py-3">
          <p className="text-[0.6875rem] leading-relaxed text-ink-faint">
            Read-only. Every figure traces to a numbered claim.
          </p>
        </div>
      </aside>
    </>
  );
}
