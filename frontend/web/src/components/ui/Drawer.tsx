import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';

import { cx } from '@/lib/cx';
import { useEscape } from '@/hooks/useHotkeys';
import { useReducedMotion } from '@/hooks/useReducedMotion';

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** A short line under the title: what this panel is for. */
  lede?: string;
  children: ReactNode;
  /** Rendered in the header, left of the close control. */
  actions?: ReactNode;
}

/**
 * A panel that slides in from the right edge.
 *
 * It is a real modal dialogue: focus moves into it on open and returns to
 * whatever opened it on close, Escape dismisses it, the scrim dismisses it, and
 * Tab is trapped inside. Glass blur is allowed — a drawer is an overlay.
 */
export function Drawer({ open, onClose, title, lede, children, actions }: DrawerProps) {
  const panel = useRef<HTMLDivElement | null>(null);
  const restore = useRef<HTMLElement | null>(null);
  const reduced = useReducedMotion();

  useEscape(open, onClose);

  useEffect(() => {
    if (!open) return;
    restore.current = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() => {
      panel.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus() ??
        panel.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
      restore.current?.focus();
    };
  }, [open]);

  // Tab stays inside the panel for as long as it is open.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !panel.current) return;
      const focusable = panel.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
      );
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          data-print="hide"
          className="fixed inset-0 z-50 flex justify-end"
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.24, ease: [0.22, 0.61, 0.36, 1] }}
        >
          <div
            aria-hidden
            onClick={onClose}
            className="absolute inset-0 bg-[rgb(var(--c-bg)/0.6)] backdrop-blur-md"
          />

          <motion.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            initial={reduced ? false : { x: 32, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={reduced ? { opacity: 0 } : { x: 24, opacity: 0 }}
            transition={{ duration: 0.38, ease: [0.22, 0.61, 0.36, 1] }}
            className={cx(
              'relative flex h-full w-full max-w-[34rem] flex-col',
              'border-l border-hairline bg-[rgb(var(--c-surface)/0.97)] shadow-overlay backdrop-blur-2xl',
            )}
          >
            <header className="flex shrink-0 items-start gap-4 border-b border-hairline px-6 py-5">
              <div className="min-w-0 flex-1">
                <h2 className="opsz-title font-serif text-[1.25rem] leading-7 tracking-[-0.01em] text-ink">
                  {title}
                </h2>
                {lede ? (
                  <p className="mt-1 text-[0.8125rem] leading-5 text-ink-faint">{lede}</p>
                ) : null}
              </div>
              {actions}
              <button
                type="button"
                onClick={onClose}
                data-autofocus
                className="-mr-1 shrink-0 rounded-sm p-1.5 text-ink-faint transition-colors duration-hover ease-editorial hover:text-ink"
              >
                <X size={16} strokeWidth={1.5} aria-hidden />
                <span className="sr-only">Close</span>
              </button>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">{children}</div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
