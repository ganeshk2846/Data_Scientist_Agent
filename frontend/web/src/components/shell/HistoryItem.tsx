import { CornerDownRight, Star } from 'lucide-react';

import { cx } from '@/lib/cx';
import { formatRelativeTime } from '@/lib/format';
import type { HistoryEntry } from '@/hooks/useSession';
import type { RunStatus } from '@/types/envelope';

/** Status reads as a dot, so the rail stays a quiet list of questions. */
const STATUS_DOT: Record<RunStatus, string> = {
  answered: 'bg-sage',
  clarify: 'bg-accent',
  refused: 'bg-ink-faint',
  blocked: 'bg-terracotta',
  insufficient_evidence: 'bg-ink-faint',
  error: 'bg-terracotta',
};

const STATUS_LABEL: Record<RunStatus, string> = {
  answered: 'Answered',
  clarify: 'Needs clarifying',
  refused: 'Refused',
  blocked: 'Blocked',
  insufficient_evidence: 'Insufficient evidence',
  error: 'Error',
};

interface HistoryItemProps {
  entry: HistoryEntry;
  active: boolean;
  onSelect: (localId: string) => void;
  onToggleStar: (localId: string) => void;
}

/**
 * One stored question.
 *
 * The star is a sibling button rather than a nested one — a button inside a
 * button is invalid and unreachable by keyboard — so the row is a flex pair and
 * the question button takes the remaining width. An unstarred star shows only
 * on hover or focus; a starred one is always visible, because that is the whole
 * point of having starred it.
 */
export function HistoryItem({ entry, active, onSelect, onToggleStar }: HistoryItemProps) {
  const pending = entry.status === null;
  const statusLabel = entry.status ? STATUS_LABEL[entry.status] : 'Running';

  return (
    <li
      className={cx(
        'group relative flex items-start rounded-sm',
        'transition-colors duration-hover ease-editorial',
        active
          ? 'bg-[rgb(var(--c-surface))] shadow-soft'
          : 'hover:bg-[rgb(var(--c-hairline)/0.45)]',
      )}
    >
      {/* The active marker is an accent hairline — the one accented thing in
          the rail, marking where the reader is. */}
      <span
        aria-hidden
        className={cx(
          'absolute left-0 top-2 bottom-2 w-px transition-colors duration-micro',
          active ? 'bg-accent' : 'bg-transparent',
        )}
      />

      <button
        type="button"
        onClick={() => onSelect(entry.localId)}
        aria-current={active ? 'true' : undefined}
        className="min-w-0 flex-1 rounded-sm px-2.5 py-2 text-left"
      >
        <span className="flex items-start gap-2">
          {entry.clarificationOf ? (
            <CornerDownRight
              size={12}
              strokeWidth={1.5}
              aria-hidden
              className="mt-[0.3rem] shrink-0 text-ink-faint"
            />
          ) : null}
          <span
            className={cx(
              'line-clamp-2 text-[0.8125rem] leading-5',
              active ? 'text-ink' : 'text-ink-muted group-hover:text-ink',
            )}
          >
            {entry.question}
          </span>
        </span>
        <span className="mt-1.5 flex items-center gap-2 pl-px">
          <span
            aria-hidden
            className={cx(
              'h-1 w-1 shrink-0 rounded-full',
              pending ? 'animate-pulse bg-accent' : STATUS_DOT[entry.status ?? 'error'],
            )}
          />
          <span className="text-[0.6875rem] leading-4 text-ink-faint">{statusLabel}</span>
          <span aria-hidden className="text-ink-faint/60">
            ·
          </span>
          <span className="text-[0.6875rem] leading-4 tabular-nums text-ink-faint">
            {formatRelativeTime(entry.askedAt)}
          </span>
        </span>
      </button>

      <button
        type="button"
        onClick={() => onToggleStar(entry.localId)}
        className={cx(
          'mt-2 mr-1.5 shrink-0 rounded-sm p-1 transition-[color,opacity] duration-hover ease-editorial',
          entry.starred
            ? 'text-accent-ink opacity-100'
            : 'text-ink-faint opacity-0 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100',
        )}
      >
        <Star
          size={12}
          strokeWidth={1.5}
          aria-hidden
          className={entry.starred ? 'fill-current' : undefined}
        />
        <span className="sr-only">
          {entry.starred ? 'Remove the star' : 'Star this question'}
        </span>
      </button>
    </li>
  );
}

/**
 * The collapsed rail shows each question as a status glyph only. The question
 * still reaches assistive tech and the tooltip, so nothing is lost — only the
 * horizontal space.
 */
export function HistoryGlyph({ entry, active, onSelect }: HistoryItemProps) {
  const pending = entry.status === null;
  const statusLabel = entry.status ? STATUS_LABEL[entry.status] : 'Running';

  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(entry.localId)}
        aria-current={active ? 'true' : undefined}
        title={`${entry.question} — ${statusLabel}`}
        className={cx(
          'relative grid h-9 w-full place-items-center rounded-sm',
          'transition-colors duration-hover ease-editorial',
          active
            ? 'bg-[rgb(var(--c-surface))] shadow-soft'
            : 'hover:bg-[rgb(var(--c-hairline)/0.5)]',
        )}
      >
        <span
          aria-hidden
          className={cx(
            'absolute left-0 top-1.5 bottom-1.5 w-px',
            active ? 'bg-accent' : 'bg-transparent',
          )}
        />
        <span
          aria-hidden
          className={cx(
            'h-1.5 w-1.5 rounded-full',
            pending ? 'animate-pulse bg-accent' : STATUS_DOT[entry.status ?? 'error'],
          )}
        />
        {entry.starred ? (
          <Star
            size={9}
            strokeWidth={1.5}
            aria-hidden
            className="absolute right-1 top-1 fill-current text-accent-ink"
          />
        ) : null}
        <span className="sr-only">
          {entry.question} — {statusLabel}
          {entry.starred ? ', starred' : ''}
        </span>
      </button>
    </li>
  );
}
