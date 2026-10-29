import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, Check, Info } from 'lucide-react';
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { cx } from '@/lib/cx';
import { useReducedMotion } from '@/hooks/useReducedMotion';

/**
 * Toasts — the quietest possible confirmation.
 *
 * A toast says that something *happened*, in one short line, and then leaves.
 * It is never a dialogue, never carries an action, and never stacks more than
 * three deep. Tone is carried by one small mark, not by a coloured panel.
 *
 * The region is a polite live region, so a screen reader hears the confirmation
 * without losing its place. `assertive` is reserved for failures.
 */

export type ToastTone = 'done' | 'note' | 'fault';

interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
  /** Optional second line: the detail, in mono, for ids and filenames. */
  detail?: string;
}

interface ToastApi {
  /** Confirms an action completed. */
  done: (message: string, detail?: string) => void;
  /** States a fact the reader should know. */
  note: (message: string, detail?: string) => void;
  /** Reports a failure. Held twice as long and announced assertively. */
  fault: (message: string, detail?: string) => void;
}

const ToastCtx = createContext<ToastApi | null>(null);

const MARK: Record<ToastTone, { Icon: typeof Check; className: string }> = {
  done: { Icon: Check, className: 'text-sage' },
  note: { Icon: Info, className: 'text-ink-faint' },
  fault: { Icon: AlertTriangle, className: 'text-terracotta' },
};

const LIFETIME: Record<ToastTone, number> = {
  done: 2_600,
  note: 3_200,
  fault: 6_000,
};

const MAX_VISIBLE = 3;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<readonly Toast[]>([]);
  const nextId = useRef(0);
  const reduced = useReducedMotion();

  const push = useCallback((tone: ToastTone, message: string, detail?: string) => {
    const id = (nextId.current += 1);
    setToasts((current) => [
      ...current.slice(-(MAX_VISIBLE - 1)),
      { id, tone, message, ...(detail ? { detail } : {}) },
    ]);
    window.setTimeout(
      () => setToasts((current) => current.filter((toast) => toast.id !== id)),
      LIFETIME[tone],
    );
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      done: (message, detail) => push('done', message, detail),
      note: (message, detail) => push('note', message, detail),
      fault: (message, detail) => push('fault', message, detail),
    }),
    [push],
  );

  const faulted = toasts.some((toast) => toast.tone === 'fault');

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div
        data-print="hide"
        role="status"
        aria-live={faulted ? 'assertive' : 'polite'}
        className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 px-4 pb-5 sm:items-end sm:px-6"
      >
        <AnimatePresence initial={false}>
          {toasts.map((toast) => {
            const { Icon, className } = MARK[toast.tone];
            return (
              <motion.div
                key={toast.id}
                layout={!reduced}
                initial={reduced ? false : { opacity: 0, y: 10, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={reduced ? { opacity: 0 } : { opacity: 0, y: 6, scale: 0.99 }}
                transition={{ duration: 0.3, ease: [0.22, 0.61, 0.36, 1] }}
                className={cx(
                  'pointer-events-auto flex max-w-[22rem] items-start gap-3 rounded-sm',
                  'border border-hairline bg-[rgb(var(--c-surface-high)/0.94)] px-3.5 py-2.5',
                  'shadow-overlay backdrop-blur-xl',
                )}
              >
                <Icon
                  size={14}
                  strokeWidth={1.5}
                  aria-hidden
                  className={cx('mt-px shrink-0', className)}
                />
                <div className="min-w-0">
                  <p className="text-[0.8125rem] leading-5 text-ink">{toast.message}</p>
                  {toast.detail ? (
                    <p className="mt-0.5 truncate font-mono text-[0.6875rem] leading-4 text-ink-muted">
                      {toast.detail}
                    </p>
                  ) : null}
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

/**
 * Safe outside a provider: the calls then simply do nothing, so a component can
 * be rendered in isolation (presentation mode, a test) without a provider.
 */
export function useToast(): ToastApi {
  return (
    useContext(ToastCtx) ?? {
      done: () => {},
      note: () => {},
      fault: () => {},
    }
  );
}
