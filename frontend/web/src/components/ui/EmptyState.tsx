import type { ReactNode } from 'react';

import { cx } from '@/lib/cx';

/**
 * An empty state: one refined hairline figure, one line of explanation, and at
 * most one thing to do.
 *
 * The figures are drawn here rather than imported, for two reasons. An icon set
 * gives you a pictogram where this wants a *drawing* — the subject rendered in
 * the same hairline weight as the rest of the product. And a drawing inherits
 * the palette through `.hairline-art`, so it re-tones with the accent instead
 * of carrying a colour of its own.
 */

export type EmptyArt = 'pinboard' | 'compare' | 'history' | 'search';

/** 120 × 72, so every state's figure occupies exactly the same block. */
function Art({ art }: { art: EmptyArt }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 120 72"
      width="120"
      height="72"
      className="overflow-visible"
    >
      {art === 'pinboard' ? (
        <g>
          {/* Three tiles on a baseline; the first carries the accent rule. */}
          <rect className="hairline-art" x="6" y="14" width="32" height="44" rx="2" />
          <rect className="hairline-art" x="44" y="14" width="32" height="44" rx="2" />
          <rect className="hairline-art" x="82" y="14" width="32" height="44" rx="2" />
          <path className="hairline-art-accent" d="M14 26 h16" />
          <path className="hairline-art" d="M52 26 h16 M90 26 h16" opacity="0.5" />
          <path className="hairline-art" d="M14 44 h10 M52 44 h10 M90 44 h10" opacity="0.5" />
          <path className="hairline-art" d="M0 64 h120" opacity="0.6" />
        </g>
      ) : null}

      {art === 'compare' ? (
        <g>
          {/* Two columns, aligned section by section, with the gutter drawn. */}
          <rect className="hairline-art" x="8" y="10" width="44" height="52" rx="2" />
          <rect className="hairline-art" x="68" y="10" width="44" height="52" rx="2" />
          <path className="hairline-art-accent" d="M60 6 v60" />
          <path
            className="hairline-art"
            d="M16 24 h28 M76 24 h28 M16 36 h20 M76 36 h20 M16 48 h24 M76 48 h24"
            opacity="0.5"
          />
        </g>
      ) : null}

      {art === 'history' ? (
        <g>
          {/* A rail of questions, the top one still open. */}
          <path className="hairline-art-accent" d="M10 12 v12" />
          <path className="hairline-art" d="M18 16 h64 M18 24 h40" opacity="0.7" />
          <path className="hairline-art" d="M10 38 v12 M10 60 v8" opacity="0.4" />
          <path
            className="hairline-art"
            d="M18 42 h52 M18 50 h30 M18 64 h44"
            opacity="0.35"
          />
        </g>
      ) : null}

      {art === 'search' ? (
        <g>
          <circle className="hairline-art" cx="52" cy="32" r="18" />
          <path className="hairline-art-accent" d="M65 45 l12 12" />
          <path className="hairline-art" d="M40 32 h24" opacity="0.4" />
        </g>
      ) : null}
    </svg>
  );
}

export function EmptyState({
  art,
  title,
  body,
  action,
  className,
}: {
  art: EmptyArt;
  title: string;
  body: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cx(
        'flex flex-col items-center px-6 py-16 text-center sm:py-20',
        className,
      )}
    >
      <Art art={art} />
      <h3 className="opsz-title mt-8 font-serif text-[1.25rem] leading-7 tracking-[-0.008em] text-ink">
        {title}
      </h3>
      <p className="mt-3 max-w-[26rem] text-[0.8125rem] leading-6 text-ink-faint">
        {body}
      </p>
      {action ? <div className="mt-7">{action}</div> : null}
    </div>
  );
}
