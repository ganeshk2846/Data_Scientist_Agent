import type { ReactNode } from 'react';

import { cx } from '@/lib/cx';

interface CardProps {
  children: ReactNode;
  className?: string;
  /** `flat` sits on the page; `raised` lifts off it; `sunken` recedes. */
  tone?: 'flat' | 'raised' | 'sunken';
  as?: 'div' | 'section' | 'article' | 'aside';
}

const TONES = {
  flat: 'bg-surface border border-hairline shadow-soft',
  raised: 'bg-raised border border-hairline shadow-lifted',
  sunken: 'bg-sunken border border-hairline',
} as const;

/** The standard surface: hairline border, soft layered shadow, generous pad. */
export function Card({ children, className, tone = 'flat', as = 'div' }: CardProps) {
  const Tag = as;
  return <Tag className={cx('rounded-sm', TONES[tone], className)}>{children}</Tag>;
}

/** A small uppercase section label — the editorial eyebrow. */
export function SectionLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx('text-micro uppercase text-ink-faint', className)}>{children}</div>
  );
}

/** A 1px warm rule. Decorative, so hidden from assistive tech. */
export function Hairline({ className }: { className?: string }) {
  return <div aria-hidden className={cx('h-px w-full bg-hairline', className)} />;
}
