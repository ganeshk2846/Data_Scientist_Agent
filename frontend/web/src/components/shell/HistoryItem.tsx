import { CornerDownRight } from 'lucide-react';

import { cx } from '@/lib/cx';
import { formatRelativeTime } from '@/lib/format';
import type { HistoryEntry } from '@/hooks/useSession';
import type { RunStatus } from '@/types/envelope';

/** Status reads as a dot, so the rail stays a quiet list of questions. */
const STATUS_DOT: Record<RunStatus, string> = {
  answered: 'bg-sage',
  clarify: 'bg-gold',
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
}

export function HistoryItem({ entry, active, onSelect }: HistoryItemProps) {
  const pending = entry.status === null;
  const statusLabel = entry.status ? STATUS_LABEL[entry.status] : 'Running';

  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(entry.localId)}
        aria-current={active ? 'true' : undefined}
        className={cx(
          'group relative w-full rounded-[3px] px-2.5 py-2 text-left',
          'transition-colors duration-micro ease-editorial',
          active ? 'bg-[rgb(var(--c-gold)/0.06)]' : 'hover:bg-[rgb(var(--c-hairline)/0.4)]',
        )}
      >
        {/* The active marker is a gold hairline, not a filled block. */}
        <span
          aria-hidden
          className={cx(
            'absolute left-0 top-2 bottom-2 w-px transition-colors duration-micro',
            active ? 'bg-gold' : 'bg-transparent',
          )}
        />
        <div className="flex items-start gap-2">
          {entry.clarificationOf ? (
            <CornerDownRight
              size={12}
              strokeWidth={1.75}
              aria-hidden
              className="mt-[0.3rem] shrink-0 text-ink-faint"
            />
          ) : null}
          <span
            className={cx(
              'line-clamp-2 text-[0.8125rem] leading-[1.35]',
              active ? 'text-ink' : 'text-ink-muted group-hover:text-ink',
            )}
          >
            {entry.question}
          </span>
        </div>
        <div className="mt-1.5 flex items-center gap-2 pl-px">
          <span
            aria-hidden
            className={cx(
              'h-1 w-1 shrink-0 rounded-full',
              pending ? 'animate-pulse bg-gold' : STATUS_DOT[entry.status ?? 'error'],
            )}
          />
          <span className="text-[0.6875rem] text-ink-faint">{statusLabel}</span>
          <span aria-hidden className="text-ink-faint/60">
            ·
          </span>
          <span className="text-[0.6875rem] tabular-nums text-ink-faint">
            {formatRelativeTime(entry.askedAt)}
          </span>
        </div>
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
          'relative grid h-9 w-full place-items-center rounded-[3px]',
          'transition-colors duration-micro ease-editorial',
          active ? 'bg-[rgb(var(--c-gold)/0.06)]' : 'hover:bg-[rgb(var(--c-hairline)/0.5)]',
        )}
      >
        <span
          aria-hidden
          className={cx(
            'absolute left-0 top-1.5 bottom-1.5 w-px',
            active ? 'bg-gold' : 'bg-transparent',
          )}
        />
        <span
          aria-hidden
          className={cx(
            'h-1.5 w-1.5 rounded-full',
            pending ? 'animate-pulse bg-gold' : STATUS_DOT[entry.status ?? 'error'],
          )}
        />
        <span className="sr-only">
          {entry.question} — {statusLabel}
        </span>
      </button>
    </li>
  );
}
