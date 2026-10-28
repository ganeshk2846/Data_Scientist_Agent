import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Tag } from '@/components/briefing/StatusBadge';
import { useChartColors } from '@/hooks/useChartColors';
import { cx } from '@/lib/cx';
import { formatNumber, formatPercent, humanise } from '@/lib/format';
import type { SeriesPoint } from '@/lib/evidence';
import type { ResolvedTheme } from '@/lib/theme';
import type { AnomalyResult } from '@/types/envelope';

interface AnomalyChartProps {
  result: AnomalyResult;
  /** Empty when no sibling lookup block supplied a usable series. */
  series: readonly SeriesPoint[];
  theme: ResolvedTheme;
}

const VERDICT_TONE = {
  unusual: 'terracotta',
  within_normal_range: 'sage',
  insufficient_evidence: 'neutral',
} as const;

/**
 * The expected band plus the actual value.
 *
 * With a sibling series we draw a line chart, the `expected_range` as a shaded
 * band and the actual marked with a gold ring. Without one we fall back to a
 * horizontal range bar — never a one-point line chart, which would imply a
 * trend the contract cannot support.
 */
export function AnomalyChart({ result, series, theme }: AnomalyChartProps) {
  const colors = useChartColors(theme);
  const [low, high] = result.expected_range;
  const outside = result.actual < low || result.actual > high;

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
        <div>
          <div className="flex items-baseline gap-3">
            <span className="font-serif text-[2.75rem] leading-[1.05] tracking-[-0.015em] tabular-nums text-ink">
              {formatNumber(result.actual)}
            </span>
            <span
              className={cx(
                'text-[0.9375rem] tabular-nums',
                outside ? 'text-terracotta' : 'text-sage',
              )}
            >
              {formatPercent(result.deviation_pct, true)}
            </span>
          </div>
          <div className="mt-2 text-[0.8125rem] text-ink-faint">
            against an expected{' '}
            <span className="tabular-nums text-ink-muted">
              {formatNumber(result.expected)}
            </span>
            <span className="mx-1.5 text-ink-faint/60">·</span>
            <span className="tabular-nums">
              range {formatNumber(low)}–{formatNumber(high)}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Tag tone={VERDICT_TONE[result.verdict]}>{humanise(result.verdict)}</Tag>
          <Tag>{humanise(result.persistence)}</Tag>
          <Tag>{humanise(result.baseline_kind)}</Tag>
        </div>
      </div>

      <div className="mt-8">
        {series.length >= 3 ? (
          <SeriesChart result={result} series={series} colors={colors} outside={outside} />
        ) : (
          <RangeBar result={result} outside={outside} />
        )}
      </div>

      <dl className="mt-7 grid gap-x-8 gap-y-2 border-t border-hairline pt-5 text-[0.6875rem] sm:grid-cols-2">
        <Row label="Robust score">
          <span className="tabular-nums">
            {formatNumber(result.robust_score, 2)} against a threshold of{' '}
            {formatNumber(result.threshold, 2)}
          </span>
        </Row>
        {result.correction_used ? (
          <Row label="Correction">{result.correction_used}</Row>
        ) : null}
        {result.calendar_effects.length > 0 ? (
          <Row label="Calendar">{result.calendar_effects.join(', ')}</Row>
        ) : null}
      </dl>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-24 shrink-0 uppercase tracking-label text-ink-faint">{label}</dt>
      <dd className="min-w-0 text-ink-muted">{children}</dd>
    </div>
  );
}

/**
 * A domain that hugs the data but still lands on round numbers.
 *
 * Handing Recharts a raw padded domain makes it label the exact bounds, which
 * produces ticks like "8,130.62". Rounding outward to a 1/2/5 step keeps the
 * axis readable without anchoring the chart at zero.
 */
function niceDomain(min: number, max: number): [number, number] {
  const range = max - min || Math.abs(max) || 1;
  const rough = range / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const normalised = rough / magnitude;
  const step = (normalised >= 5 ? 5 : normalised >= 2 ? 2 : 1) * magnitude;
  return [Math.floor(min / step) * step, Math.ceil(max / step) * step];
}

/**
 * The tooltip is written by hand: Recharts would otherwise list `bandBase` and
 * `bandHeight`, which are internal stacking series and mean nothing to a reader.
 */
function ChartTooltip({
  active,
  label,
  payload,
  colors,
}: {
  active?: boolean;
  label?: string | number;
  payload?: readonly { dataKey?: string | number; value?: number }[];
  colors: ReturnType<typeof useChartColors>;
}) {
  if (!active || !payload) return null;
  const point = payload.find((entry) => entry.dataKey === 'value');
  if (!point || typeof point.value !== 'number') return null;

  return (
    <div
      className="rounded-[3px] border border-hairline bg-raised px-3 py-2 shadow-overlay"
      style={{ borderColor: colors.hairlineStrong }}
    >
      <div className="text-micro uppercase tracking-label text-ink-faint">{label}</div>
      <div className="mt-1 font-mono text-[0.8125rem] tabular-nums text-ink">
        {formatNumber(point.value)}
      </div>
    </div>
  );
}

function SeriesChart({
  result,
  series,
  colors,
  outside,
}: {
  result: AnomalyResult;
  series: readonly SeriesPoint[];
  colors: ReturnType<typeof useChartColors>;
  outside: boolean;
}) {
  const [low, high] = result.expected_range;
  // The band is a stacked area: a transparent base up to `low`, then its height.
  const data = series.map((point) => ({
    label: point.label,
    value: point.value,
    bandBase: low,
    bandHeight: Math.max(0, high - low),
  }));

  const actualLabel = data[data.length - 1]?.label ?? '';

  // Hug the data and the band rather than anchoring at zero: a series sitting
  // in the top third of an empty chart reads as a flat line.
  const values = [...series.map((point) => point.value), low, high, result.actual];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.12 || Math.abs(max) * 0.1 || 1;
  const domain = niceDomain(min - pad, max + pad);

  return (
    <div className="h-64 w-full sm:h-72">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 12, right: 24, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={colors.hairline} strokeDasharray="2 5" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: colors.inkFaint, fontSize: 10 }}
            stroke={colors.hairline}
            tickLine={false}
            axisLine={{ stroke: colors.hairline }}
            minTickGap={24}
          />
          <YAxis
            tick={{ fill: colors.inkFaint, fontSize: 10 }}
            stroke="transparent"
            tickLine={false}
            axisLine={false}
            width={52}
            domain={domain}
            tickFormatter={(value: number) => formatNumber(value)}
          />
          <Tooltip
            content={<ChartTooltip colors={colors} />}
            cursor={{ stroke: colors.hairlineStrong, strokeWidth: 1 }}
          />

          {/* The shaded expected band, kept deliberately faint. */}
          <Area
            dataKey="bandBase"
            stackId="band"
            stroke="none"
            fill="transparent"
            isAnimationActive={false}
            activeDot={false}
          />
          <Area
            dataKey="bandHeight"
            stackId="band"
            stroke="none"
            fill={colors.gold}
            fillOpacity={0.09}
            isAnimationActive={false}
            activeDot={false}
          />

          {/* The expected value. */}
          <ReferenceLine
            y={result.expected}
            stroke={colors.gold}
            strokeDasharray="3 5"
            strokeWidth={1}
            strokeOpacity={0.75}
          />

          <Line
            type="monotone"
            dataKey="value"
            stroke={colors.series[0]}
            strokeWidth={1.5}
            dot={false}
            activeDot={{
              r: 3.5,
              fill: colors.gold,
              stroke: colors.surface,
              strokeWidth: 2,
            }}
            animationDuration={900}
            animationEasing="ease-out"
          />

          {/* The period under test: a filled core inside a gold ring. */}
          <ReferenceDot
            x={actualLabel}
            y={result.actual}
            r={6}
            fill="none"
            stroke={colors.gold}
            strokeWidth={1.5}
            isFront
          />
          <ReferenceDot
            x={actualLabel}
            y={result.actual}
            r={2.75}
            fill={outside ? colors.terracotta : colors.sage}
            stroke="none"
            isFront
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * The single-period fallback: a shaded `expected_range` band, a tick for
 * `expected`, and a marked point for `actual`.
 */
function RangeBar({ result, outside }: { result: AnomalyResult; outside: boolean }) {
  const [low, high] = result.expected_range;
  const values = [low, high, result.actual, result.expected];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.18 || Math.abs(max) * 0.1 || 1;
  const from = min - pad;
  const span = max + pad - from || 1;
  const at = (value: number) => ((value - from) / span) * 100;

  return (
    <div>
      <div className="relative h-20">
        <div aria-hidden className="absolute inset-x-0 top-10 h-px bg-hairline" />

        <div
          aria-hidden
          className="absolute top-[1.625rem] h-7 rounded-[2px] bg-[var(--c-gold-wash)] ring-1 ring-inset ring-[rgb(var(--c-gold)/0.3)]"
          style={{ left: `${at(low)}%`, width: `${at(high) - at(low)}%` }}
        />

        <div
          aria-hidden
          className="absolute top-[1.25rem] h-10 w-px bg-gold"
          style={{ left: `${at(result.expected)}%` }}
        />
        <div
          className="absolute top-0 -translate-x-1/2 whitespace-nowrap text-[0.6875rem] text-gold-ink"
          style={{ left: `${at(result.expected)}%` }}
        >
          expected
        </div>

        {/* The actual: a gold ring around a verdict-coloured core. */}
        <div
          aria-hidden
          className="absolute top-[2rem] h-4 w-4 -translate-x-1/2 rounded-full border border-gold"
          style={{ left: `${at(result.actual)}%` }}
        />
        <div
          aria-hidden
          className={cx(
            'absolute top-[2.3125rem] h-2 w-2 -translate-x-1/2 rounded-full',
            outside ? 'bg-terracotta' : 'bg-sage',
          )}
          style={{ left: `${at(result.actual)}%` }}
        />
        <div
          className={cx(
            'absolute top-[3.25rem] -translate-x-1/2 whitespace-nowrap text-[0.6875rem] tabular-nums',
            outside ? 'text-terracotta' : 'text-sage',
          )}
          style={{ left: `${at(result.actual)}%` }}
        >
          {formatNumber(result.actual)} · {formatPercent(result.deviation_pct, true)}
        </div>
      </div>

      <div className="mt-2 flex justify-between font-mono text-[0.6875rem] tabular-nums text-ink-faint">
        <span>{formatNumber(low)}</span>
        <span className="text-micro uppercase tracking-label">expected range</span>
        <span>{formatNumber(high)}</span>
      </div>

      <p className="mt-5 max-w-prose text-[0.6875rem] leading-relaxed text-ink-faint">
        One period under test. The contract supplies no historical series for this
        result, so no trend is drawn.
      </p>
    </div>
  );
}
