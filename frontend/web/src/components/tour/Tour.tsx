import { AnimatePresence, motion } from 'framer-motion';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { Hairline } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import { useEscape } from '@/hooks/useHotkeys';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { TOUR_STEPS, type TourStep } from '@/lib/tour';

/**
 * The first-run tour: a spotlight and four cards.
 *
 * The scrim is one SVG rect with a mask cut out of it, so there is a single
 * darkened plane with a hole in it rather than four panels that have to meet
 * exactly at the corners — four panels is where a 1px seam always shows up.
 *
 * Steps whose target is not on the page are skipped, not pointed at. On the
 * hero there is no pipeline and no lineage yet, so a first run shows the two
 * steps that exist and the rest wait until there is an answer on screen.
 */

interface Spot {
  step: TourStep;
  rect: { top: number; left: number; width: number; height: number };
}

const PAD = 8;

function measure(step: TourStep): Spot | null {
  const node = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
  if (!node) return null;
  const box = node.getBoundingClientRect();
  if (box.width < 8 || box.height < 8) return null;
  return {
    step,
    rect: {
      top: box.top - PAD,
      left: box.left - PAD,
      width: box.width + PAD * 2,
      height: box.height + PAD * 2,
    },
  };
}

export function Tour({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const [spot, setSpot] = useState<Spot | null>(null);
  const reduced = useReducedMotion();

  useEscape(open, onClose);

  /** Only the steps whose target is actually on the page, in order. */
  const available = useMemo(() => {
    if (!open) return [];
    return TOUR_STEPS.filter((step) =>
      document.querySelector(`[data-tour="${step.target}"]`),
    );
  }, [open]);

  useEffect(() => {
    if (open) setIndex(0);
  }, [open]);

  // Re-measure on scroll and resize: the spotlight has to stay on its target.
  useEffect(() => {
    if (!open) return;
    const step = available[index];
    if (!step) {
      setSpot(null);
      return;
    }
    const update = () => setSpot(measure(step));
    update();
    window.addEventListener('scroll', update, true);
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
    };
  }, [available, index, open]);

  const total = available.length;
  const last = index >= total - 1;

  const next = useCallback(() => {
    if (last) onClose();
    else setIndex((value) => value + 1);
  }, [last, onClose]);

  if (!open || total === 0) return null;

  // The card sits below the spotlight when there is room, above when not.
  const below = spot ? spot.rect.top + spot.rect.height + 16 : 120;
  const above = spot ? spot.rect.top - 16 : 120;
  const fitsBelow = below + 210 < window.innerHeight;

  return (
    <AnimatePresence>
      <motion.div
        data-print="hide"
        className="fixed inset-0 z-[55]"
        initial={reduced ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.3, ease: [0.22, 0.61, 0.36, 1] }}
      >
        {/* One plane, one hole. */}
        <svg
          aria-hidden
          className="absolute inset-0 h-full w-full"
          onClick={onClose}
        >
          <defs>
            <mask id="tour-mask">
              <rect x="0" y="0" width="100%" height="100%" fill="#fff" />
              {spot ? (
                <rect
                  x={spot.rect.left}
                  y={spot.rect.top}
                  width={spot.rect.width}
                  height={spot.rect.height}
                  rx="4"
                  fill="#000"
                />
              ) : null}
            </mask>
          </defs>
          <rect
            x="0"
            y="0"
            width="100%"
            height="100%"
            fill="rgb(var(--c-bg) / 0.86)"
            mask="url(#tour-mask)"
          />
          {spot ? (
            <rect
              x={spot.rect.left + 0.5}
              y={spot.rect.top + 0.5}
              width={spot.rect.width - 1}
              height={spot.rect.height - 1}
              rx="3.5"
              fill="none"
              stroke="rgb(var(--c-accent))"
              strokeWidth="1"
            />
          ) : null}
        </svg>

        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label="Introduction"
          initial={reduced ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.34, ease: [0.22, 0.61, 0.36, 1] }}
          className={cx(
            'edge-accent absolute left-1/2 w-[min(26rem,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-sm',
            'border border-hairline-strong bg-[rgb(var(--c-surface-high)/0.97)] shadow-overlay backdrop-blur-xl',
          )}
          style={
            fitsBelow
              ? { top: `${below}px` }
              : { top: `${Math.max(16, above - 200)}px` }
          }
        >
          <div className="px-6 pb-5 pt-5">
            <div className="flex items-baseline justify-between gap-4">
              <p className="text-micro uppercase tracking-label text-accent-ink">
                {available[index]?.eyebrow}
              </p>
              <p className="text-micro uppercase tracking-label tabular-nums text-ink-faint">
                {index + 1} / {total}
              </p>
            </div>
            <h2 className="opsz-title mt-3 font-serif text-[1.25rem] leading-7 tracking-[-0.01em] text-ink">
              {available[index]?.title}
            </h2>
            <p className="mt-2.5 text-[0.8125rem] leading-6 text-ink-muted">
              {available[index]?.body}
            </p>
          </div>

          <Hairline />

          <div className="flex items-center gap-3 px-6 py-3">
            {/* Progress as four rules, not a bar: the same language as the
                pipeline's miniature track. */}
            <span aria-hidden className="flex items-center gap-1.5">
              {available.map((step, position) => (
                <span
                  key={step.target}
                  className={cx(
                    'h-px w-4 transition-colors duration-micro',
                    position <= index ? 'bg-accent' : 'bg-hairline-strong',
                  )}
                />
              ))}
            </span>

            <button
              type="button"
              onClick={onClose}
              className="ml-auto rounded-sm px-2 py-1 text-[0.75rem] text-ink-faint transition-colors duration-hover ease-editorial hover:text-ink"
            >
              Skip
            </button>
            <button
              type="button"
              onClick={next}
              className="rounded-sm border border-accent bg-accent px-3.5 py-1.5 text-[0.75rem] font-medium text-on-accent transition-[filter] duration-hover ease-editorial hover:brightness-[1.06]"
            >
              {last ? 'Begin' : 'Next'}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
