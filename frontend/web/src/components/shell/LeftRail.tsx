import {
  ChevronLeft,
  ChevronRight,
  Columns2,
  LayoutGrid,
  MessageSquare,
  Plus,
  Search,
  X,
} from 'lucide-react';
import { useId, useMemo, useState } from 'react';

import { HistoryItem, HistoryGlyph } from './HistoryItem';
import { Hairline } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import type { HistoryEntry } from '@/hooks/useSession';

export type View = 'ask' | 'pinboard' | 'compare';
export type HistoryFilter = 'all' | 'starred' | 'answered' | 'attention';

const FILTERS: readonly { value: HistoryFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'starred', label: 'Starred' },
  { value: 'answered', label: 'Answered' },
  { value: 'attention', label: 'Needs attention' },
];

/**
 * Which statuses count as "needs attention": everything that did not land on a
 * finished answer. A run still in flight is not one of them — it has not had a
 * chance to need anything yet.
 */
function needsAttention(entry: HistoryEntry): boolean {
  return (
    entry.status !== null &&
    entry.status !== 'answered'
  );
}

export function matchesFilter(entry: HistoryEntry, filter: HistoryFilter): boolean {
  switch (filter) {
    case 'starred':
      return entry.starred;
    case 'answered':
      return entry.status === 'answered';
    case 'attention':
      return needsAttention(entry);
    case 'all':
      return true;
  }
}

interface LeftRailProps {
  history: readonly HistoryEntry[];
  activeId: string | null;
  view: View;
  pinCount: number;
  open: boolean;
  collapsed: boolean;
  onSelect: (localId: string) => void;
  onToggleStar: (localId: string) => void;
  onNewQuestion: () => void;
  onSetView: (view: View) => void;
  onClose: () => void;
  onToggleCollapsed: () => void;
}

/**
 * The rail: where this browser's questions live, and the way between the three
 * views.
 *
 * Collapsed, it keeps the three view marks and one glyph per question, so the
 * product is still navigable at 4rem wide. The filters and the search field
 * only appear once there is enough history for them to be worth the space —
 * a filter row above two questions is furniture, not a tool.
 */
export function LeftRail({
  history,
  activeId,
  view,
  pinCount,
  open,
  collapsed,
  onSelect,
  onToggleStar,
  onNewQuestion,
  onSetView,
  onClose,
  onToggleCollapsed,
}: LeftRailProps) {
  const [filter, setFilter] = useState<HistoryFilter>('all');
  const [query, setQuery] = useState('');
  const searchId = useId();

  const views: readonly { value: View; label: string; Icon: typeof LayoutGrid; badge?: number }[] =
    [
      { value: 'ask', label: 'Ask', Icon: MessageSquare },
      { value: 'pinboard', label: 'Pinboard', Icon: LayoutGrid, badge: pinCount },
      { value: 'compare', label: 'Compare', Icon: Columns2 },
    ];

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return history.filter(
      (entry) =>
        matchesFilter(entry, filter) &&
        (!needle || entry.question.toLowerCase().includes(needle)),
    );
  }, [filter, history, query]);

  const tools = history.length >= 3;

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
        aria-label="Navigation and stored questions"
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
        {/* ── The three views ─────────────────────────────────────────────── */}
        <nav
          aria-label="Views"
          className={cx('shrink-0 pt-3', collapsed ? 'lg:px-2' : 'px-2')}
        >
          <ul className="space-y-0.5">
            {views.map(({ value, label, Icon, badge }) => {
              const active = view === value;
              return (
                <li key={value}>
                  <button
                    type="button"
                    onClick={() => onSetView(value)}
                    aria-current={active ? 'page' : undefined}
                    title={collapsed ? label : undefined}
                    className={cx(
                      'relative flex w-full items-center gap-2.5 rounded-sm py-2',
                      'transition-colors duration-hover ease-editorial',
                      collapsed ? 'lg:justify-center lg:px-0' : 'px-2.5',
                      active
                        ? 'bg-[rgb(var(--c-surface))] shadow-soft'
                        : 'hover:bg-[rgb(var(--c-hairline)/0.45)]',
                    )}
                  >
                    <Icon
                      size={15}
                      strokeWidth={1.5}
                      aria-hidden
                      className={cx(
                        'shrink-0',
                        active ? 'text-ink' : 'text-ink-faint',
                      )}
                    />
                    {!collapsed ? (
                      <>
                        <span
                          className={cx(
                            'min-w-0 flex-1 text-left text-[0.8125rem] leading-5',
                            active ? 'text-ink' : 'text-ink-muted',
                          )}
                        >
                          {label}
                        </span>
                        {badge ? (
                          <span className="shrink-0 font-mono text-[0.6875rem] tabular-nums text-ink-faint">
                            {badge}
                          </span>
                        ) : null}
                      </>
                    ) : (
                      <span className="sr-only">{label}</span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <Hairline className="mt-3" />

        {/* ── The history header ──────────────────────────────────────────── */}
        <div
          className={cx(
            'flex h-11 shrink-0 items-center gap-1',
            collapsed ? 'lg:justify-center lg:px-0' : 'px-3',
          )}
        >
          {!collapsed ? (
            <span className="flex-1 pl-1 text-micro uppercase tracking-label text-ink-faint">
              Questions
            </span>
          ) : null}

          <button
            type="button"
            onClick={onNewQuestion}
            title="New question (N)"
            className="rounded-sm p-1.5 text-ink-faint transition-colors duration-hover hover:text-ink"
          >
            <Plus size={15} strokeWidth={1.5} aria-hidden />
            <span className="sr-only">Ask a new question</span>
          </button>

          {!collapsed ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded-sm p-1.5 text-ink-faint transition-colors duration-hover hover:text-ink lg:hidden"
            >
              <X size={15} strokeWidth={1.5} aria-hidden />
              <span className="sr-only">Close the rail</span>
            </button>
          ) : null}
        </div>

        {/* ── Search and filters, once there is history worth filtering ──── */}
        {!collapsed && tools ? (
          <div className="shrink-0 space-y-2.5 px-3 pb-3">
            <div className="relative">
              <Search
                size={13}
                strokeWidth={1.5}
                aria-hidden
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint"
              />
              <input
                id={searchId}
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search questions"
                aria-label="Search stored questions"
                className={cx(
                  'w-full rounded-sm border border-hairline bg-[rgb(var(--c-surface)/0.6)]',
                  'py-1.5 pl-8 pr-2.5 text-[0.8125rem] leading-5 text-ink',
                  'placeholder:text-ink-faint transition-colors duration-hover ease-editorial',
                  'hover:border-hairline-strong',
                )}
              />
            </div>

            <div
              role="radiogroup"
              aria-label="Filter stored questions"
              className="flex flex-wrap gap-1"
            >
              {FILTERS.map((option) => {
                const active = filter === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setFilter(option.value)}
                    className={cx(
                      'rounded-sm px-2 py-1 text-[0.6875rem] leading-4',
                      'transition-colors duration-hover ease-editorial',
                      active
                        ? 'bg-[rgb(var(--c-surface))] text-ink shadow-soft'
                        : 'text-ink-faint hover:text-ink-muted',
                    )}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        {/* ── The questions ───────────────────────────────────────────────── */}
        <nav
          aria-label="Stored questions"
          className={cx(
            'min-h-0 flex-1 overflow-y-auto pb-2.5',
            collapsed ? 'lg:px-2' : 'px-2',
          )}
        >
          {history.length === 0 ? (
            !collapsed ? (
              <p className="px-2.5 py-5 text-[0.8125rem] leading-6 text-ink-faint">
                Questions collect here, stored in this browser. Select one to
                reopen its briefing.
              </p>
            ) : null
          ) : shown.length === 0 ? (
            !collapsed ? (
              <p className="px-2.5 py-5 text-[0.8125rem] leading-6 text-ink-faint">
                Nothing matches that filter.
              </p>
            ) : null
          ) : (
            <ul className="space-y-0.5">
              {shown.map((entry) =>
                collapsed ? (
                  <HistoryGlyph
                    key={entry.localId}
                    entry={entry}
                    active={entry.localId === activeId}
                    onSelect={onSelect}
                    onToggleStar={onToggleStar}
                  />
                ) : (
                  <HistoryItem
                    key={entry.localId}
                    entry={entry}
                    active={entry.localId === activeId}
                    onSelect={onSelect}
                    onToggleStar={onToggleStar}
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
            <p className="flex-1 text-[0.6875rem] leading-4 text-ink-faint">
              Read-only. Stored in this browser.
            </p>
          ) : null}
          <button
            type="button"
            title={collapsed ? 'Expand the rail' : 'Collapse the rail'}
            onClick={onToggleCollapsed}
            className="hidden rounded-sm p-1.5 text-ink-faint transition-colors duration-hover hover:text-ink lg:block"
          >
            {collapsed ? (
              <ChevronRight size={14} strokeWidth={1.5} aria-hidden />
            ) : (
              <ChevronLeft size={14} strokeWidth={1.5} aria-hidden />
            )}
            <span className="sr-only">
              {collapsed ? 'Expand the rail' : 'Collapse the rail'}
            </span>
          </button>
        </div>
      </aside>
    </>
  );
}
