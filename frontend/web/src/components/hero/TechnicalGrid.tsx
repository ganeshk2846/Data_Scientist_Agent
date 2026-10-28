import { useReducedMotion } from '@/hooks/useReducedMotion';

/**
 * A faint gold technical grid behind the hero — the drafting paper a precision
 * instrument is designed on.
 *
 * Two superimposed grids (a fine 24px rule and a heavier 120px rule) drift
 * slowly on independent cycles, so the movement never reads as a loop. A radial
 * mask fades it out at the edges so it has no visible boundary; the CSS
 * `prefers-reduced-motion` reset freezes it, and a reduced-motion reader gets
 * the static grid with no animation attached at all.
 */
export function TechnicalGrid() {
  const reduced = useReducedMotion();

  return (
    <div
      aria-hidden
      data-print="hide"
      className="pointer-events-none absolute inset-0 overflow-hidden"
      style={{
        // The mask is what keeps this from looking like a cheap tiled texture.
        maskImage:
          'radial-gradient(74% 62% at 50% 38%, #000 0%, rgba(0,0,0,0.55) 46%, transparent 78%)',
        WebkitMaskImage:
          'radial-gradient(74% 62% at 50% 38%, #000 0%, rgba(0,0,0,0.55) 46%, transparent 78%)',
      }}
    >
      {/* Fine rule. */}
      <div
        className={reduced ? '' : 'animate-[grid-drift_72s_linear_infinite]'}
        style={{
          position: 'absolute',
          inset: '-20%',
          backgroundImage:
            'linear-gradient(to right, var(--c-grid) 0 1px, transparent 1px 100%),' +
            'linear-gradient(to bottom, var(--c-grid) 0 1px, transparent 1px 100%)',
          backgroundSize: '24px 24px',
          opacity: 0.5,
        }}
      />
      {/* Heavier rule, drifting the other way, for depth. */}
      <div
        className={reduced ? '' : 'animate-[grid-drift-slow_124s_linear_infinite]'}
        style={{
          position: 'absolute',
          inset: '-20%',
          backgroundImage:
            'linear-gradient(to right, var(--c-grid) 0 1px, transparent 1px 100%),' +
            'linear-gradient(to bottom, var(--c-grid) 0 1px, transparent 1px 100%)',
          backgroundSize: '120px 120px',
          opacity: 0.85,
        }}
      />
      {/* A single horizon rule, to give the stage a floor. */}
      <div
        className="absolute inset-x-0 top-[38%] h-px"
        style={{
          background:
            'linear-gradient(90deg, transparent, var(--c-grid), var(--c-grid), transparent)',
        }}
      />
    </div>
  );
}
