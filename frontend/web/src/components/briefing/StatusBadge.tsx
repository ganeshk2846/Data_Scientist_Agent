import { cx } from '@/lib/cx';
import type { RunStatus } from '@/types/envelope';

/**
 * Status reads as a small lettered badge. Tone is carried by a hairline border
 * and a wash, never a filled block of colour.
 */
const TONE: Record<RunStatus, string> = {
  answered: 'border-sage text-sage bg-sage-wash',
  clarify: 'border-gold text-gold bg-[var(--c-gold-wash)]',
  refused: 'border-hairline-strong text-ink-muted bg-sunken',
  blocked: 'border-terracotta text-terracotta bg-terracotta-wash',
  insufficient_evidence: 'border-hairline-strong text-ink-muted bg-sunken',
  error: 'border-terracotta text-terracotta bg-terracotta-wash',
};

export const STATUS_LABEL: Record<RunStatus, string> = {
  answered: 'Answered',
  clarify: 'Needs clarifying',
  refused: 'Refused',
  blocked: 'Blocked',
  insufficient_evidence: 'Insufficient evidence',
  error: 'Error',
};

export function StatusBadge({
  status,
  className,
}: {
  status: RunStatus;
  className?: string;
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center rounded-sm border px-2.5 py-1 text-micro uppercase',
        TONE[status],
        className,
      )}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

/** A neutral hairline tag, used for route labels and small contract values. */
export function Tag({
  children,
  tone = 'neutral',
  className,
  title,
}: {
  children: React.ReactNode;
  tone?: 'neutral' | 'gold' | 'sage' | 'terracotta';
  className?: string;
  title?: string;
}) {
  const tones = {
    neutral: 'border-hairline-strong text-ink-muted',
    gold: 'border-gold text-gold bg-[var(--c-gold-wash)]',
    sage: 'border-sage text-sage bg-sage-wash',
    terracotta: 'border-terracotta text-terracotta bg-terracotta-wash',
  } as const;
  return (
    <span
      title={title}
      className={cx(
        'inline-flex items-center rounded-sm border px-2 py-0.5 text-micro uppercase',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
