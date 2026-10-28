import { motion } from 'framer-motion';

import { useReducedMotion } from '@/hooks/useReducedMotion';
import { formatConfidence } from '@/lib/format';

/**
 * Route confidence as a small 180° arc.
 *
 * The `RouterResult` validator rejects anything below 0.70 that is not a pure
 * clarify route, so real answered runs all sit in 0.70–1.00. Scaling the arc
 * 0.5–1.0 keeps those values legible instead of pinned to the right edge — and
 * the exact figure is always printed beside it, so the scaling never misleads.
 * Clarify routes can legitimately come in below 0.5 (0.2 observed), so the
 * fraction is clamped.
 */
const FLOOR = 0.5;

export function ConfidenceGauge({ confidence }: { confidence: number }) {
  const reduced = useReducedMotion();
  const clamped = Math.min(1, Math.max(0, confidence));
  const fraction = Math.min(1, Math.max(0, (clamped - FLOOR) / (1 - FLOOR)));

  const radius = 26;
  const length = Math.PI * radius;
  const path = `M 4 32 A ${radius} ${radius} 0 0 1 56 32`;

  return (
    <div className="flex items-center gap-3">
      <svg
        width="60"
        height="36"
        viewBox="0 0 60 36"
        aria-hidden
        className="overflow-visible"
      >
        <path
          d={path}
          fill="none"
          stroke="rgb(var(--c-hairline))"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <motion.path
          d={path}
          fill="none"
          stroke="rgb(var(--c-gold))"
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray={length}
          initial={reduced ? false : { strokeDashoffset: length }}
          animate={{ strokeDashoffset: length * (1 - fraction) }}
          transition={{ duration: reduced ? 0 : 0.6, ease: [0.22, 0.61, 0.36, 1] }}
        />
      </svg>

      <div className="leading-tight">
        <div className="font-serif text-[1.375rem] tabular-nums text-ink">
          {formatConfidence(clamped)}
        </div>
        <div className="text-micro uppercase text-ink-faint">Route confidence</div>
      </div>
    </div>
  );
}
