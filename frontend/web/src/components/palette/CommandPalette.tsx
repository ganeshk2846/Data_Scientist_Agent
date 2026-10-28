import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowRight,
  Clock,
  Command,
  CornerDownLeft,
  FlaskConical,
  MonitorPlay,
  Moon,
  Plus,
  Search,
  Sparkles,
  Sun,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { SUGGESTIONS } from '@/components/ask/SuggestionChips';
import { Kbd } from '@/components/ui/Button';
import { useEscape } from '@/hooks/useHotkeys';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { cx } from '@/lib/cx';
import { formatRelativeTime } from '@/lib/format';
import type { HistoryEntry } from '@/hooks/useSession';

export interface PaletteActions {
  onAsk: (question: string) => void;
  onOpenHistory: (localId: string) => void;
  onNewQuestion: () => void;
  onToggleTheme: () => void;
  onToggleMock: () => void;
  onPresentationMode: () => void;
}

interface CommandPaletteProps extends PaletteActions {
  open: boolean;
  onClose: () => void;
  history: readonly HistoryEntry[];
  mock: boolean;
  themeLabel: string;
  canPresent: boolean;
}

interface Row {
  id: string;
  group: 'Ask' | 'Session' | 'Actions';
  label: string;
  hint?: string;
  Icon: typeof Search;
  run: () => void;
  /** What the query matches against. */
  search: string;
}

/**
 * The command palette. One surface for asking, reopening a past answer, and
 * the handful of actions worth a keystroke.
 *
 * Deliberately not a fuzzy matcher: substring matching over a short, curated
 * list is predictable, and predictability is what makes a palette feel fast.
 */
export function CommandPalette({
  open,
  onClose,
  history,
  mock,
  themeLabel,
  canPresent,
  onAsk,
  onOpenHistory,
  onNewQuestion,
  onToggleTheme,
  onToggleMock,
  onPresentationMode,
}: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const reduced = useReducedMotion();

  useEscape(open, onClose);

  // Fresh every time it opens — a palette that remembers its last query is
  // a palette that makes you delete something first.
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setCursor(0);
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  const rows = useMemo<Row[]>(() => {
    const act = (run: () => void) => () => {
      onClose();
      run();
    };

    const asks: Row[] = SUGGESTIONS.map((question, index) => ({
      id: `ask-${index}`,
      group: 'Ask',
      label: question,
      hint: 'verified',
      Icon: Sparkles,
      search: question,
      run: act(() => onAsk(question)),
    }));

    const past: Row[] = history
      .filter((entry) => entry.envelope)
      .slice(0, 6)
      .map((entry) => ({
        id: `hist-${entry.localId}`,
        group: 'Session',
        label: entry.question,
        hint: formatRelativeTime(entry.askedAt),
        Icon: Clock,
        search: entry.question,
        run: act(() => onOpenHistory(entry.localId)),
      }));

    const actions: Row[] = [
      {
        id: 'new',
        group: 'Actions',
        label: 'New question',
        Icon: Plus,
        search: 'new question reset clear',
        run: act(onNewQuestion),
      },
      {
        id: 'theme',
        group: 'Actions',
        label: `Theme — ${themeLabel}`,
        hint: 'cycles',
        Icon: themeLabel === 'Dark' ? Moon : Sun,
        search: 'theme dark light system appearance',
        run: act(onToggleTheme),
      },
      {
        id: 'mock',
        group: 'Actions',
        label: mock ? 'Leave mock mode' : 'Enter mock mode',
        hint: 'reloads',
        Icon: FlaskConical,
        search: 'mock sample demo preview offline',
        run: act(onToggleMock),
      },
      ...(canPresent
        ? [
            {
              id: 'present',
              group: 'Actions' as const,
              label: 'Presentation mode',
              hint: 'P',
              Icon: MonitorPlay,
              search: 'present presentation fullscreen share clean',
              run: act(onPresentationMode),
            },
          ]
        : []),
    ];

    const all = [...asks, ...past, ...actions];
    const needle = query.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((row) => row.search.toLowerCase().includes(needle));
  }, [
    canPresent,
    history,
    mock,
    onAsk,
    onClose,
    onNewQuestion,
    onOpenHistory,
    onPresentationMode,
    onToggleMock,
    onToggleTheme,
    query,
    themeLabel,
  ]);

  // A free-text question is always offered, so the palette can ask anything.
  const freeText = query.trim();
  const total = rows.length + (freeText ? 1 : 0);
  const clampedCursor = total === 0 ? 0 : Math.min(cursor, total - 1);

  useEffect(() => setCursor(0), [query]);

  // Keep the active row in view without yanking the whole page.
  useEffect(() => {
    const node = listRef.current?.querySelector('[data-active="true"]');
    node?.scrollIntoView({ block: 'nearest' });
  }, [clampedCursor]);

  const invoke = (index: number) => {
    if (freeText && index === 0) {
      onClose();
      onAsk(freeText);
      return;
    }
    rows[index - (freeText ? 1 : 0)]?.run();
  };

  if (!open && reduced) return null;

  let lastGroup: Row['group'] | null = null;

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh] sm:pt-[16vh]"
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.22, ease: [0.22, 0.61, 0.36, 1] }}
        >
          <div
            aria-hidden
            onClick={onClose}
            className="absolute inset-0 bg-[rgb(var(--c-bg)/0.62)] backdrop-blur-xl"
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            initial={reduced ? false : { opacity: 0, y: -10, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.99 }}
            transition={{ duration: 0.32, ease: [0.22, 0.61, 0.36, 1] }}
            className={cx(
              'edge-gold relative w-full max-w-xl overflow-hidden rounded-[4px]',
              'border border-hairline-strong bg-[rgb(var(--c-surface-raised)/0.94)]',
              'shadow-overlay backdrop-blur-2xl',
            )}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                setCursor((value) => (total === 0 ? 0 : (value + 1) % total));
              } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                setCursor((value) => (total === 0 ? 0 : (value - 1 + total) % total));
              } else if (event.key === 'Enter') {
                event.preventDefault();
                invoke(clampedCursor);
              }
            }}
          >
            {/* Query */}
            <div className="flex items-center gap-3 border-b border-hairline px-4">
              <Search size={15} strokeWidth={1.75} aria-hidden className="text-ink-faint" />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Ask a question, or jump to…"
                aria-label="Command palette query"
                className="h-12 flex-1 bg-transparent text-body text-ink outline-none placeholder:text-ink-faint focus-visible:outline-none"
              />
              <Kbd>Esc</Kbd>
            </div>

            {/* Rows */}
            <div ref={listRef} className="max-h-[52vh] overflow-y-auto py-1.5">
              {freeText ? (
                <PaletteRow
                  active={clampedCursor === 0}
                  Icon={ArrowRight}
                  label={`Ask “${freeText}”`}
                  hint="unverified"
                  onPick={() => invoke(0)}
                />
              ) : null}

              {rows.map((row, index) => {
                const position = index + (freeText ? 1 : 0);
                const showGroup = row.group !== lastGroup;
                lastGroup = row.group;
                return (
                  <div key={row.id}>
                    {showGroup ? (
                      <div className="px-4 pb-1.5 pt-3 text-micro uppercase tracking-label text-ink-faint">
                        {row.group}
                      </div>
                    ) : null}
                    <PaletteRow
                      active={clampedCursor === position}
                      Icon={row.Icon}
                      label={row.label}
                      {...(row.hint ? { hint: row.hint } : {})}
                      onPick={() => invoke(position)}
                    />
                  </div>
                );
              })}

              {total === 0 ? (
                <p className="px-4 py-8 text-center text-small text-ink-faint">
                  Nothing matches. Type a question and press Enter to ask it.
                </p>
              ) : null}
            </div>

            {/* Footer hints */}
            <div className="flex items-center gap-4 border-t border-hairline px-4 py-2.5 text-[0.6875rem] text-ink-faint">
              <span className="flex items-center gap-1.5">
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd>
                <span className="ml-0.5">navigate</span>
              </span>
              <span className="flex items-center gap-1.5">
                <Kbd>
                  <CornerDownLeft size={10} strokeWidth={2} aria-hidden />
                </Kbd>
                <span className="ml-0.5">select</span>
              </span>
              <span className="ml-auto flex items-center gap-2 text-ink-faint">
                <Command size={10} strokeWidth={2} aria-hidden />
                <span className="uppercase tracking-label">Command</span>
              </span>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function PaletteRow({
  active,
  Icon,
  label,
  hint,
  onPick,
}: {
  active: boolean;
  Icon: typeof Search;
  label: ReactNode;
  hint?: string;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      data-active={active}
      onMouseMove={undefined}
      onClick={onPick}
      className={cx(
        'relative flex w-full items-center gap-3 px-4 py-2.5 text-left',
        'transition-colors duration-150 ease-editorial',
        // A full gold wash reads muddy over the raised surface; the selection
        // is carried by the gold rule and the brighter text instead.
        active ? 'bg-[rgb(var(--c-gold)/0.055)]' : 'hover:bg-[rgb(var(--c-hairline)/0.4)]',
      )}
    >
      <span
        aria-hidden
        className={cx(
          'absolute inset-y-0 left-0 w-[2px] transition-colors duration-150',
          active ? 'bg-gold' : 'bg-transparent',
        )}
      />
      <Icon
        size={14}
        strokeWidth={1.75}
        aria-hidden
        className={cx('shrink-0', active ? 'text-gold-ink' : 'text-ink-muted')}
      />
      <span
        className={cx(
          'min-w-0 flex-1 truncate text-[0.875rem]',
          active ? 'text-ink' : 'text-ink-muted',
        )}
      >
        {label}
      </span>
      {/* The hint is context, not a column of labels: it shows on the active
          row only, so the list reads as questions rather than as a table. */}
      {hint ? (
        <span
          className={cx(
            'shrink-0 text-micro uppercase tracking-label transition-opacity duration-150',
            active ? 'text-ink-faint opacity-100' : 'opacity-0',
          )}
        >
          {hint}
        </span>
      ) : null}
    </button>
  );
}
