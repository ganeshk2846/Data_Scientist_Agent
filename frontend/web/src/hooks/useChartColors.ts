import { useEffect, useState } from 'react';

import type { ResolvedTheme } from '@/lib/theme';

/**
 * Recharts needs concrete colour strings, and its own defaults are not allowed
 * (they include purples). So we read the resolved tokens off the document and
 * re-read them whenever the theme changes — the tokens stay the single source
 * of truth and nothing is hard-coded here.
 */
export interface ChartColors {
  gold: string;
  goldSoft: string;
  sage: string;
  terracotta: string;
  ink: string;
  inkMuted: string;
  inkFaint: string;
  hairline: string;
  hairlineStrong: string;
  surface: string;
  series: readonly [string, string, string, string];
}

const VARS = {
  gold: '--c-gold',
  goldSoft: '--c-gold-soft',
  sage: '--c-sage',
  terracotta: '--c-terracotta',
  ink: '--c-ink',
  inkMuted: '--c-ink-muted',
  inkFaint: '--c-ink-faint',
  hairline: '--c-hairline',
  hairlineStrong: '--c-hairline-strong',
  surface: '--c-surface',
} as const;

/** Tokens are stored as "R G B" channels; Recharts wants a usable colour. */
function channelsToRgb(raw: string, fallback: string): string {
  const parts = raw.trim().split(/\s+/);
  if (parts.length !== 3) return fallback;
  return `rgb(${parts.join(' ')})`;
}

function read(): ChartColors {
  const style = getComputedStyle(document.documentElement);
  const value = (name: string, fallback: string) =>
    channelsToRgb(style.getPropertyValue(name), fallback);

  return {
    gold: value(VARS.gold, 'rgb(184 151 90)'),
    goldSoft: value(VARS.goldSoft, 'rgb(223 207 168)'),
    sage: value(VARS.sage, 'rgb(107 127 98)'),
    terracotta: value(VARS.terracotta, 'rgb(168 92 69)'),
    ink: value(VARS.ink, 'rgb(28 27 25)'),
    inkMuted: value(VARS.inkMuted, 'rgb(85 82 76)'),
    inkFaint: value(VARS.inkFaint, 'rgb(138 133 124)'),
    hairline: value(VARS.hairline, 'rgb(226 220 208)'),
    hairlineStrong: value(VARS.hairlineStrong, 'rgb(207 199 184)'),
    surface: value(VARS.surface, 'rgb(253 251 247)'),
    series: [
      value('--c-series-1', 'rgb(154 147 138)'),
      value('--c-series-2', 'rgb(180 173 162)'),
      value('--c-series-3', 'rgb(125 118 110)'),
      value('--c-series-4', 'rgb(200 193 181)'),
    ],
  };
}

export function useChartColors(theme: ResolvedTheme): ChartColors {
  const [colors, setColors] = useState<ChartColors>(read);

  useEffect(() => {
    // The token swap happens on the same tick as the attribute change, so one
    // frame of delay is enough to read the new values.
    const handle = window.requestAnimationFrame(() => setColors(read()));
    return () => window.cancelAnimationFrame(handle);
  }, [theme]);

  return colors;
}
