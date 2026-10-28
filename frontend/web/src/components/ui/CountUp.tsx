import { useEffect, useRef, useState } from 'react';

import { useReducedMotion } from '@/hooks/useReducedMotion';
import { formatNumber } from '@/lib/format';

/**
 * Counts a figure up to its final value.
 *
 * SAFE-8 note: this animates the *presentation* of a number the envelope
 * already contains — it never derives one. The final frame is always the
 * envelope's own value put through `formatNumber`, the intermediate frames are
 * `aria-hidden`, and the accessible name is the final value from the first
 * render. Under reduced motion it prints the final value immediately.
 */
export function CountUp({
  value,
  fractionDigits,
  className,
  durationMs = 900,
}: {
  value: number;
  fractionDigits?: number;
  className?: string;
  durationMs?: number;
}) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(() => (reduced ? value : 0));
  const frame = useRef(0);

  useEffect(() => {
    if (reduced || !Number.isFinite(value)) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / durationMs);
      // Ease-out quint: fast, then a long settle. Never overshoots.
      const eased = 1 - Math.pow(1 - progress, 5);
      setShown(value * eased);
      if (progress < 1) frame.current = window.requestAnimationFrame(tick);
    };
    frame.current = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame.current);
  }, [value, durationMs, reduced]);

  const settled = shown === value;
  const digits = fractionDigits ?? (Number.isInteger(value) ? 0 : 2);

  return (
    <span className={className}>
      {/* The animating text is decorative; the real value is announced once. */}
      <span aria-hidden className="tabular-nums">
        {formatNumber(settled ? value : shown, digits)}
      </span>
      <span className="sr-only">{formatNumber(value, digits)}</span>
    </span>
  );
}
