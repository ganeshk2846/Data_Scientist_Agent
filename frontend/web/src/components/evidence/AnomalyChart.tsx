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
 * With a sibling series we draw a proper line chart, the `expected_range` as a
 * shaded band and the actual marked. Without one we fall back to a horizontal
 * range bar — never a one-point line chart, which would imply a trend that the
 * contract cannot support.
 */
export function AnomalyChart({ result, series, theme }: AnomalyChartProps) {
  const colors = useChartColors(theme);
  const [low, high] = result.expected_range;
  const outside = result.actual < low || result.actual > high;
  const tone = outside ? colors.terracotta : colors.sage;

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div>
          <div className="text-micro uppercase text-ink-faint">{result.window}</div>
          <div className="mt-1.5 flex items-baseline gap-3">
            <span className="font-serif text-figure tabular-nums text-ink">
              {formatNumber(result.actual)}
            </span>
            <span
              className={cx(
                'text-body tabular-nums',
                outside ? 'text-terracotta' : 'text-sage',
              )}
            >
              {formatPercent(result.deviation_pct, true)}
            </span>
          </div>
          <div className="mt-1 text-small text-ink-faint">
            against an expected{' '}
            <span className="tabular-nums text-ink-muted">
              {formatNumber(result.expected)}
            </span>{' '}
            (
            <span className="tabular-nums">
              {formatNumber(low)}–{formatNumber(high)}
            </span>
            )
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Tag tone={VERDICT_TONE[result.verdict]}>{humanise(result.verdict)}</Tag>
          <Tag>{humanise(result.persistence)}</Tag>
          <Tag>{humanise(result.baseline_kind)}</Tag>
        </div>
      </div>

      <div className="mt-7">
        {series.length >= 3 ? (
          <SeriesChart result={result} series={series} colors={colors} tone={tone} />
        ) : (
          <RangeBar result={result} outside={outside} />
        )}
      </div>

      {result.calendar_effects.length > 0 || result.correction_used ? (
        <dl className="mt-6 space-y-1.5 text-[0.6875rem] text-ink-faint">
          {result.correction_used ? (
            <div className="flex gap-3">
              <dt className="w-24 shrink-0 uppercase">Correction</dt>
              <dd className="text-ink-muted">{result.correction_used}</dd>
            </div>
          ) : null}
          {result.calendar_effects.length > 0 ? (
            <div className="flex gap-3">
              <dt className="w-24 shrink-0 uppercase">Calendar</dt>
              <dd className="text-ink-muted">{result.calendar_effects.join(', ')}</dd>
            </div>
          ) : null}
          <div className="flex gap-3">
            <dt className="w-24 shrink-0 uppercase">Robust score</dt>
            <dd className="tabular-nums text-ink-muted">
              {formatNumber(result.robust_score, 2)} against a threshold of{' '}
              {formatNumber(result.threshold, 2)}
            </dd>
          </div>
        </dl>
      ) : null}
    </div>
  );
}

function SeriesChart({
  result,
  series,
  colors,
  tone,
}: {
  result: AnomalyResult;
  series: readonly SeriesPoint[];
  colors: ReturnType<typeof useChartColors>;
  tone: string;
}) {
  const [low, high] = result.expected_range;
  // The band is drawn as a stacked area: a transparent base to `low`, then the
  // band height on top of it.
  const data = series.map((point) => ({
    label: point.label,
    value: point.value,
    bandBase: low,
    bandHeight: Math.max(0, high - low),
  }));

  const lastIndex = data.length - 1;
  const actualLabel = data[lastIndex]?.label ?? '';

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={colors.hairline} strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: colors.inkFaint, fontSize: 11 }}
            stroke={colors.hairline}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: colors.inkFaint, fontSize: 11 }}
            stroke={colors.hairline}
            tickLine={false}
            width={56}
            tickFormatter={(value: number) => formatNumber(value)}
          />
          <Tooltip
            contentStyle={{
              background: colors.surface,
              border: `1px solid ${colors.hairline}`,
              borderRadius: 2,
              fontSize: 12,
              color: colors.ink,
            }}
            labelStyle={{ color: colors.inkFaint }}
            formatter={(value: number, name) =>
              name === 'value' ? [formatNumber(value), 'actual'] : null
            }
          />

          {/* The shaded expected band. */}
          <Area
            dataKey="bandBase"
            stackId="band"
            stroke="none"
            fill="transparent"
            isAnimationActive={false}
          />
          <Area
            dataKey="bandHeight"
            stackId="band"
            stroke="none"
            fill={colors.gold}
            fillOpacity={0.14}
            isAnimationActive={false}
          />

          <ReferenceLine
            y={result.expected}
            stroke={colors.gold}
            strokeDasharray="4 4"
            strokeWidth={1}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={colors.series[2]}
            strokeWidth={1.75}
            dot={false}
            animationDuration={600}
            animationEasing="ease-out"
          />
          {/* The period under test. */}
          <ReferenceDot
            x={actualLabel}
            y={result.actual}
            r={4.5}
            fill={tone}
            stroke={colors.surface}
            strokeWidth={2}
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
        {/* The axis. */}
        <div aria-hidden className="absolute inset-x-0 top-10 h-px bg-hairline" />

        {/* The expected range. */}
        <div
          aria-hidden
          className="absolute top-[1.625rem] h-7 rounded-sm bg-[var(--c-gold-wash)] ring-1 ring-inset ring-[rgb(var(--c-gold)/0.35)]"
          style={{ left: `${at(low)}%`, width: `${at(high) - at(low)}%` }}
        />

        {/* The expected value. */}
        <div
          aria-hidden
          className="absolute top-[1.25rem] h-10 w-px bg-gold"
          style={{ left: `${at(result.expected)}%` }}
        />
        <div
          className="absolute top-0 -translate-x-1/2 whitespace-nowrap text-[0.6875rem] text-gold"
          style={{ left: `${at(result.expected)}%` }}
        >
          expected
        </div>

        {/* The actual value. */}
        <div
          aria-hidden
          className={cx(
            'absolute top-[2.125rem] h-3.5 w-3.5 -translate-x-1/2 rounded-full ring-2 ring-[rgb(var(--c-surface))]',
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
        <span className="text-micro uppercase tracking-wide">expected range</span>
        <span>{formatNumber(high)}</span>
      </div>

      <p className="mt-4 max-w-prose text-[0.6875rem] leading-relaxed text-ink-faint">
        One period under test. The contract supplies no historical series for this
        result, so no trend is drawn.
      </p>
    </div>
  );
}
