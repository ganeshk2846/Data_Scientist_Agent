import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { useEffect, useRef } from 'react';

import { Kbd } from '@/components/ui/Button';
import { Hairline } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import { useEscape } from '@/hooks/useHotkeys';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { SHORTCUTS, SHORTCUT_GROUPS } from '@/lib/shortcuts';

/**
 * The shortcuts sheet.
 *
 * Rendered *from* `lib/shortcuts.ts`, which is also what the handlers are
 * named after — so the sheet cannot fall out of step with the keyboard. Two
 * columns of groups on a wide screen, one on a narrow one, with the keycaps
 * right-aligned on a single rail so the eye can run down them.
 */
export function ShortcutsSheet({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement | null>(null);
  const reduced = useReducedMotion();

  useEscape(open, onClose);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => panel.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          data-print="hide"
          className="fixed inset-0 z-50 flex items-center justify-center px-4 py-10"
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.24, ease: [0.22, 0.61, 0.36, 1] }}
        >
          <div
            aria-hidden
            onClick={onClose}
            className="absolute inset-0 bg-[rgb(var(--c-bg)/0.66)] backdrop-blur-xl"
          />

          <motion.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-label="Keyboard shortcuts"
            tabIndex={-1}
            initial={reduced ? false : { opacity: 0, y: 12, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.995 }}
            transition={{ duration: 0.34, ease: [0.22, 0.61, 0.36, 1] }}
            className={cx(
              'edge-accent relative flex max-h-full w-full max-w-2xl flex-col overflow-hidden rounded-lg',
              'border border-hairline-strong bg-[rgb(var(--c-surface-high)/0.96)]',
              'shadow-overlay backdrop-blur-2xl',
            )}
          >
            <header className="flex shrink-0 items-start justify-between gap-6 px-7 pb-5 pt-6 sm:px-9 sm:pt-7">
              <div>
                <p className="text-micro uppercase tracking-label text-ink-faint">
                  Reference
                </p>
                <h2 className="opsz-title mt-2 font-serif text-[1.5rem] leading-8 tracking-[-0.012em] text-ink">
                  The keyboard
                </h2>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="-mr-1.5 -mt-1 rounded-sm p-1.5 text-ink-faint transition-colors duration-hover ease-editorial hover:text-ink"
              >
                <X size={16} strokeWidth={1.5} aria-hidden />
                <span className="sr-only">Close</span>
              </button>
            </header>

            <Hairline />

            <div className="min-h-0 flex-1 overflow-y-auto px-7 py-7 sm:px-9">
              <div className="grid gap-x-12 gap-y-8 sm:grid-cols-2">
                {SHORTCUT_GROUPS.map((group) => (
                  <section key={group}>
                    <h3 className="text-micro uppercase tracking-label text-ink-faint">
                      {group}
                    </h3>
                    <dl className="mt-4 space-y-3">
                      {SHORTCUTS.filter((shortcut) => shortcut.group === group).map(
                        (shortcut) => (
                          <div
                            key={shortcut.keys.join('+')}
                            className="flex items-baseline gap-4"
                          >
                            <dt className="min-w-0 flex-1 text-[0.8125rem] leading-5 text-ink-muted">
                              {shortcut.label}
                            </dt>
                            <dd
                              aria-hidden
                              className="flex shrink-0 items-center gap-1"
                            >
                              {shortcut.keys.map((key) => (
                                <Kbd key={key}>{key}</Kbd>
                              ))}
                            </dd>
                          </div>
                        ),
                      )}
                    </dl>
                  </section>
                ))}
              </div>
            </div>

            <Hairline />

            <footer className="flex shrink-0 items-center gap-3 px-7 py-3.5 sm:px-9">
              <p className="text-[0.6875rem] leading-4 text-ink-faint">
                Single letters are inert while you are typing, and inert with any
                modifier held.
              </p>
              <span aria-hidden className="ml-auto flex items-center gap-1.5">
                <Kbd>Esc</Kbd>
              </span>
            </footer>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
