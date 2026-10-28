import { ChevronLeft, ChevronRight, Plus, X } from 'lucide-react';

import { HistoryItem, HistoryGlyph } from './HistoryItem';
import { Hairline } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import type { HistoryEntry } from '@/hooks/useSession';

interface LeftRailProps {
  history: readonly HistoryEntry[];
  activeId: string | null;
  open: boolean;
  collapsed: boolean;
  onSelect: (localId: string) => void;
  onNewQuestion: () => void;
  onClose: () => void;
  onToggleCollapsed: () => void;
}

export function LeftRail({
  history,
  activeId,
  open,
  collapsed,
  onSelect,
  onNewQuestion,
  onClose,
  onToggleCollapsed,
}: LeftRailProps) {
  return (
    <>
      {/* Mobile scrim. Glass blur is reserved for overlays like this one. */}
      <div
        aria-hidden
        onClick={onClose}
        className={cx(
          'fixed inset-0 z-30 bg-[rgb(var(--c-bg)/0.6)] backdrop-blur-sm lg:hidden',
          'transition-opacity duration-micro ease-editorial',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      />

      <aside
        aria-label="This session"
        data-print="hide"
        className={cx(
          'fixed inset-y-0 left-0 z-40 flex flex-col border-r border-hairline bg-sunken',
          'transition-transform duration-reveal ease-editorial',
          'lg:sticky lg:top-14 lg:z-0 lg:h-[calc(100vh-3.5rem)] lg:translate-x-0',
          // Width is animated on desktop, so collapsing feels mechanical.
          'w-rail lg:transition-[width,transform] lg:duration-reveal',
          collapsed ? 'lg:w-rail-collapsed' : 'lg:w-rail',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div
          className={cx(
            'flex h-14 shrink-0 items-center gap-1 lg:h-12',
            collapsed ? 'lg:justify-center lg:px-0' : 'px-3',
          )}
        >
          {!collapsed ? (
            <span className="flex-1 pl-1 text-micro uppercase tracking-label text-ink-faint">
              Session
            </span>
          ) : null}

          <button
            type="button"
            onClick={onNewQuestion}
            aria-label="Ask a new question"
            title="New question"
            className="rounded-[3px] p-1.5 text-ink-faint transition-colors duration-micro hover:text-gold"
          >
            <Plus size={15} strokeWidth={1.75} aria-hidden />
          </button>

          {!collapsed ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close history"
              className="rounded-[3px] p-1.5 text-ink-faint transition-colors duration-micro hover:text-ink lg:hidden"
            >
              <X size={15} strokeWidth={1.75} aria-hidden />
            </button>
          ) : null}
        </div>

        <Hairline />

        <nav
          className={cx(
            'min-h-0 flex-1 overflow-y-auto py-2.5',
            collapsed ? 'lg:px-2' : 'px-2',
          )}
        >
          {history.length === 0 ? (
            !collapsed ? (
              <p className="px-2.5 py-5 text-[0.8125rem] leading-relaxed text-ink-faint">
                Questions collect here. Select one to reopen its briefing.
              </p>
            ) : null
          ) : (
            <ul className="space-y-0.5">
              {history.map((entry) =>
                collapsed ? (
                  <HistoryGlyph
                    key={entry.localId}
                    entry={entry}
                    active={entry.localId === activeId}
                    onSelect={onSelect}
                  />
                ) : (
                  <HistoryItem
                    key={entry.localId}
                    entry={entry}
                    active={entry.localId === activeId}
                    onSelect={onSelect}
                  />
                ),
              )}
            </ul>
          )}
        </nav>

        <Hairline />

        <div
          className={cx(
            'flex shrink-0 items-center gap-2',
            collapsed ? 'lg:justify-center lg:px-0 lg:py-2.5' : 'px-3 py-2.5',
          )}
        >
          {!collapsed ? (
            <p className="flex-1 text-[0.6875rem] leading-relaxed text-ink-faint">
              Read-only. Every figure traces to a claim.
            </p>
          ) : null}
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? 'Expand the rail' : 'Collapse the rail'}
            title={collapsed ? 'Expand' : 'Collapse'}
            className="hidden rounded-[3px] p-1.5 text-ink-faint transition-colors duration-micro hover:text-ink lg:block"
          >
            {collapsed ? (
              <ChevronRight size={14} strokeWidth={1.75} aria-hidden />
            ) : (
              <ChevronLeft size={14} strokeWidth={1.75} aria-hidden />
            )}
          </button>
        </div>
      </aside>
    </>
  );
}
