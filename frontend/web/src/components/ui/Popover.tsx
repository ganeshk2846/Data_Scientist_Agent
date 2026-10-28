import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, type ReactNode } from 'react';

import { cx } from '@/lib/cx';
import { useEscape } from '@/hooks/useHotkeys';
import { useReducedMotion } from '@/hooks/useReducedMotion';

interface PopoverProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  /** Flip to the right edge when the anchor sits near the left margin. */
  align?: 'left' | 'center';
  className?: string;
}

/**
 * A small floating panel, anchored to a `relative` parent. Glass blur is
 * allowed here — overlays are the one place the rules permit it. Escape closes
 * it, and so does a click anywhere outside.
 */
export function Popover({ open, onClose, children, align = 'center', className }: PopoverProps) {
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

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          ref={panel}
          role="dialog"
          initial={reduced ? false : { opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduced ? { opacity: 0 } : { opacity: 0, y: 4 }}
          transition={{ duration: 0.3, ease: [0.22, 0.61, 0.36, 1] }}
          className={cx(
            'absolute bottom-full z-40 mb-2 w-[min(21rem,calc(100vw-2.5rem))]',
            'rounded-sm border border-hairline bg-[rgb(var(--c-surface-raised)/0.94)] p-4',
            'text-left shadow-overlay backdrop-blur-md',
            align === 'center' ? 'left-1/2 -translate-x-1/2' : 'left-0',
            className,
          )}
        >
          {children}
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
