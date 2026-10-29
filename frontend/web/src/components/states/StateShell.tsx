import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { Card, Hairline, SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';

type Tone = 'accent' | 'terracotta' | 'neutral';

const ICON_TONE: Record<Tone, string> = {
  accent: 'border-accent bg-[var(--c-accent-wash)] text-accent',
  terracotta: 'border-terracotta bg-terracotta-wash text-terracotta',
  neutral: 'border-hairline-strong bg-sunken text-ink-muted',
};

interface StateShellProps {
  Icon: LucideIcon;
  eyebrow: string;
  title: string;
  /** The contract's own words, in serif — never a bare error string. */
  lede?: string | null;
  tone?: Tone;
  children?: ReactNode;
}

/**
 * The common frame for every non-answered status. Each state says what
 * happened, shows whatever the contract gave us, and offers a way forward.
 */
export function StateShell({
  Icon,
  eyebrow,
  title,
  lede,
  tone = 'neutral',
  children,
}: StateShellProps) {
  return (
    <Card className="p-6 sm:p-9">
      <div className="flex items-start gap-5">
        <span
          className={cx(
            'mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-full border',
            ICON_TONE[tone],
          )}
        >
          <Icon size={17} strokeWidth={1.5} aria-hidden />
        </span>

        <div className="min-w-0 flex-1">
          <SectionLabel>{eyebrow}</SectionLabel>
          <h2 className="mt-2.5 font-serif text-h2 text-ink">{title}</h2>
          {lede ? (
            <p className="mt-4 max-w-prose font-serif text-body-serif font-light text-ink-muted">
              {lede}
            </p>
          ) : null}
        </div>
      </div>

      {children ? (
        <>
          <Hairline className="my-7" />
          {children}
        </>
      ) : null}
    </Card>
  );
}

/** A labelled block of the contract's own text. */
export function StateField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div>
      <SectionLabel>{label}</SectionLabel>
      <div className="mt-2.5 max-w-prose text-body leading-relaxed text-ink">
        {children}
      </div>
    </div>
  );
}
