import { motion } from 'framer-motion';

import { useReducedMotion } from '@/hooks/useReducedMotion';
import { formatConfidence } from '@/lib/format';

/**
 * Route confidence as a 180° arc.
 *
 * The `RouterResult` validator rejects anything below 0.70 that is not a pure
 * clarify route, so real answered runs all sit in 0.70–1.00. Scaling the arc
 * 0.5–1.0 keeps those legible instead of pinned to the right edge — and the
 * exact figure is always printed beside it, so the scaling never misleads.
 * Clarify routes can legitimately come in below the floor (0.2 observed), so
 * the fraction is clamped.
 */
const FLOOR = 0.5;

const WIDTH = 72;
const STROKE = 2;
const RADIUS = (WIDTH - STROKE * 2) / 2;
const BASELINE = STROKE + RADIUS;
const ARC = `M ${STROKE} ${BASELINE} A ${RADIUS} ${RADIUS} 0 0 1 ${WIDTH - STROKE} ${BASELINE}`;
const LENGTH = Math.PI * RADIUS;

export function ConfidenceGauge({ confidence }: { confidence: number }) {
  const reduced = useReducedMotion();
  const clamped = Math.min(1, Math.max(0, confidence));
  const fraction = Math.min(1, Math.max(0, (clamped - FLOOR) / (1 - FLOOR)));

  return (
    <div className="flex items-end gap-4">
      <div className="relative shrink-0" style={{ width: WIDTH, height: BASELINE + 1 }}>
        <svg width={WIDTH} height={BASELINE + 1} viewBox={`0 0 ${WIDTH} ${BASELINE + 1}`} aria-hidden>
          {/* The full travel, so the filled arc is read against something. */}
          <path
            d={ARC}
            fill="none"
            stroke="rgb(var(--c-hairline-strong))"
            strokeWidth={STROKE}
            strokeLinecap="round"
          />
          <motion.path
            d={ARC}
            fill="none"
            stroke="rgb(var(--c-ink))"
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={LENGTH}
            initial={reduced ? false : { strokeDashoffset: LENGTH }}
            animate={{ strokeDashoffset: LENGTH * (1 - fraction) }}
            transition={{ duration: reduced ? 0 : 0.9, ease: [0.22, 0.61, 0.36, 1] }}
          />
          {/* End caps, so the scale's bounds are explicit. */}
          <circle cx={STROKE} cy={BASELINE} r={0.75} fill="rgb(var(--c-ink-faint))" />
          <circle
            cx={WIDTH - STROKE}
            cy={BASELINE}
            r={0.75}
            fill="rgb(var(--c-ink-faint))"
          />
        </svg>
      </div>

      <div className="leading-none">
        <div className="font-serif text-[1.75rem] tabular-nums text-ink">
          {formatConfidence(clamped)}
        </div>
        <div className="mt-2 text-micro uppercase tracking-label text-ink-faint">
          Route confidence
        </div>
      </div>
      <span className="sr-only">
        Route confidence {formatConfidence(clamped)}, shown on a 50 to 100 percent
        scale.
      </span>
    </div>
  );
}
