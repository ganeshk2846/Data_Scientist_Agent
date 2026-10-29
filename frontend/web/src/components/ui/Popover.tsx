import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, type ReactNode } from 'react';

import { cx } from '@/lib/cx';
import { useEscape } from '@/hooks/useHotkeys';
import { useReducedMotion } from '@/hooks/useReducedMotion';

interface PopoverProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  /** Which side of the anchor it opens on. */
  placement?: 'top' | 'bottom';
  /** Which edge it aligns to, when the anchor sits near a margin. */
  align?: 'left' | 'center' | 'right';
  /** Overrides the default width, for a panel of pickers. */
  width?: string;
  className?: string;
  label?: string;
}

/**
 * A small floating panel, anchored to a `relative` parent. Glass blur is
 * allowed here — overlays are the one place the rules permit it. Escape closes
 * it, and so does a pointer anywhere outside.
 */
export function Popover({
  open,
  onClose,
  children,
  placement = 'top',
  align = 'center',
  width,
  className,
  label,
}: PopoverProps) {
  const panel = useRef<HTMLDivElement | null>(null);
  const reduced = useReducedMotion();

  useEscape(open, onClose);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!panel.current) return;
      if (!panel.current.contains(event.target as Node)) onClose();
    };
    // Defer, so the click that opened it does not immediately close it.
    const timer = window.setTimeout(
      () => document.addEventListener('pointerdown', onPointerDown),
      0,
    );
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [open, onClose]);

  const offset = placement === 'top' ? -4 : 4;

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          ref={panel}
          role="dialog"
          {...(label ? { 'aria-label': label } : {})}
          initial={reduced ? false : { opacity: 0, y: offset }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduced ? { opacity: 0 } : { opacity: 0, y: offset }}
          transition={{ duration: 0.3, ease: [0.22, 0.61, 0.36, 1] }}
          className={cx(
            'absolute z-40',
            placement === 'top' ? 'bottom-full mb-2' : 'top-full mt-2',
            'rounded-sm border border-hairline bg-[rgb(var(--c-surface-high)/0.95)] p-4',
            'text-left shadow-overlay backdrop-blur-xl',
            align === 'center'
              ? 'left-1/2 -translate-x-1/2'
              : align === 'right'
                ? 'right-0'
                : 'left-0',
            className,
          )}
          style={{ width: width ?? 'min(21rem, calc(100vw - 2.5rem))' }}
        >
          {children}
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
