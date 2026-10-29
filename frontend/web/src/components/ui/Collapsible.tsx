import { AnimatePresence, motion } from 'framer-motion';
import { ChevronRight } from 'lucide-react';
import { useId, useState, type ReactNode } from 'react';

import { cx } from '@/lib/cx';
import { useReducedMotion } from '@/hooks/useReducedMotion';

interface CollapsibleProps {
  /** Rendered inside the trigger, left of the chevron. */
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  triggerClassName?: string;
}

export function Collapsible({
  summary,
  children,
  defaultOpen = false,
  className,
  triggerClassName,
}: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen);
  const reduced = useReducedMotion();
  const panelId = useId();

  return (
    <div className={className}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={panelId}
        className={cx(
          'flex w-full items-center gap-3 text-left',
          'transition-colors duration-micro ease-editorial',
          triggerClassName,
        )}
      >
        <ChevronRight
          size={14}
          strokeWidth={1.5}
          aria-hidden
          className={cx(
            'shrink-0 text-ink-faint transition-transform duration-micro ease-editorial',
            open && 'rotate-90',
          )}
        />
        <span className="min-w-0 flex-1">{summary}</span>
      </button>

      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            id={panelId}
            initial={reduced ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={reduced ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={{ duration: 0.45, ease: [0.22, 0.61, 0.36, 1] }}
            className="overflow-hidden"
          >
            {children}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
