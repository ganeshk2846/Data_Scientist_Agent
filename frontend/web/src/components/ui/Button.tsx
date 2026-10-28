import type { ButtonHTMLAttributes, ReactNode } from 'react';

import { cx } from '@/lib/cx';

type Variant = 'primary' | 'quiet' | 'ghost';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: Variant;
}

const VARIANTS: Record<Variant, string> = {
  // Gold is the single accent; on it, ink text keeps AA contrast.
  primary:
    'bg-gold text-on-gold border border-gold hover:brightness-[1.06] active:brightness-[0.96]',
  quiet:
    'bg-surface text-ink border border-hairline-strong hover:bg-[var(--c-gold-wash)] hover:border-gold',
  ghost: 'bg-transparent text-ink-muted border border-transparent hover:text-ink',
};

export function Button({ children, variant = 'quiet', className, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-sm px-4 py-2',
        'text-small font-medium transition-colors duration-micro ease-editorial',
        'disabled:cursor-not-allowed disabled:opacity-45',
        VARIANTS[variant],
        className,
      )}
    >
      {children}
    </button>
  );
}

/** A keycap, for the hints next to the ask box. */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd
      className={cx(
        'inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-[3px] px-1.5',
        'border border-hairline-strong bg-surface',
        'font-sans text-[0.6875rem] font-medium text-ink-muted',
      )}
    >
      {children}
    </kbd>
  );
}
