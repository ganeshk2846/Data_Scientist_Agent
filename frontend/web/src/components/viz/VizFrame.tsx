import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { ChartFrame } from '@/components/evidence/ChartFrame';
import { DataTable } from '@/components/evidence/DataTable';
import { useChartColors, type ChartColors } from '@/hooks/useChartColors';
import { safeFilename } from '@/lib/download';
import { formatCompact, formatNumber } from '@/lib/format';
import type { ResolvedTheme } from '@/lib/theme';
import {
  numberAt,
  readPath,
  resolveViz,
  specColumns,
  textAt,
  type Record_,
} from '@/lib/vizData';
import type { AnswerEnvelope } from '@/types/envelope';
import type { VisualizationSpec } from '@/types/v2';

/**
 * Renders any `VisualizationSpec` (contracts.md §7) against the rows the
 * envelope already carries. It reads `kind` and `encoding` and draws; it never
 * decides what chart the data deserves (build-plan Track 5, work item 1).
 *
 * SAFE-8: every mark is a cell the backend sent. Reshaping rows into one
 * object per x value (so several series can share an axis) moves cells, it
 * does not combine them. A waterfall is drawn as contributions from zero
 * rather than as stacked running totals, because a running total would be a
 * figure of ours.
 *
 * Lazy-loaded, like `AnomalyChart`: Recharts stays out of the initial bundle.
 */
export function VizFrame({
  spec,
  envelope,
  theme,
}: {
  spec: VisualizationSpec;
  envelope: AnswerEnvelope;
  theme: ResolvedTheme;
}) {
  const colors = useChartColors(theme);
  const resolved = resolveViz(envelope, spec);

  if (!resolved) {
    return (
      <p className="text-small text-ink-muted">
        The rows for this chart were not carried in the answer, so it is not drawn.
      </p>
    );
  }

  const columns = specColumns(spec);
  const table = (
    <DataTable
      columns={columns.map((name) => ({ name }))}
      rows={resolved.records.map((record) => columns.map((name) => readPath(record, name) ?? null))}
      label={`${spec.title}, as a table`}
      csvFilename={safeFilename([spec.title, spec.viz_id], 'csv')}
      footnote={spec.source_query_id ?? spec.source_artifact_id ?? spec.viz_id}
    />
  );

  const marks = spec.annotations.filter((note) => note.kind !== 'label' || note.at.x);

  return (
    <div>
      {spec.kind === 'table' ? (
        table
      ) : (
        <ChartFrame
          subject={spec.title}
          filename={safeFilename([spec.title, spec.viz_id], 'png')}
          table={table}
        >
          <div
            role="img"
            aria-label={`${spec.title}. ${spec.caption}`}
            className="h-64 w-full sm:h-72"
          >
            <Chart spec={spec} records={resolved.records} colors={colors} />
          </div>
        </ChartFrame>
      )}

      {spec.kind === 'waterfall' ? (
        <p className="mt-3 text-[0.75rem] text-ink-faint">
          Each bar is one contribution drawn from zero; no running total is added.
        </p>
      ) : null}

      {marks.length > 0 ? (
        <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-1.5" aria-label="Marked on the chart">
          {marks.map((note, index) => (
            <li
              key={`${note.label}-${index}`}
              className="inline-flex items-center gap-2 text-[0.75rem] text-ink-muted"
            >
              <span
                aria-hidden
                className={
                  note.emphasis === 'attention'
                    ? 'h-2 w-2 rounded-full bg-accent'
                    : 'h-2 w-2 rounded-full border border-hairline-strong'
                }
              />
              {note.label}
              {note.claim_id ? (
                <span className="font-mono text-[0.6875rem] text-ink-faint">{note.claim_id}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/* ---------- the drawing ---------- */

type Row = Record<string, string | number | null | readonly [number, number]>;

const UNSPLIT = '__value';

/**
 * One object per x value with a key per series. The x values keep the order
 * the backend sent them in; nothing is sorted or aggregated — a duplicated
 * (x, series) pair keeps its first cell and the table still shows them all.
 */
function pivot(spec: VisualizationSpec, records: readonly Record_[]): { rows: Row[]; keys: string[] } {
  const { x, y, series } = spec.encoding;
  const rows: Row[] = [];
  const index = new Map<string, Row>();
  const keys: string[] = [];
  for (const record of records) {
    const xValue = textAt(record, x.column);
    const key = series ? textAt(record, series.column) || 'Total' : UNSPLIT;
    if (!keys.includes(key)) keys.push(key);
    let row = index.get(xValue);
    if (!row) {
      row = { x: xValue };
      index.set(xValue, row);
      rows.push(row);
    }
    if (!(key in row)) row[key] = numberAt(record, y.column);
  }
  return { rows, keys };
}

function seriesColour(colors: ChartColors, index: number, total: number): string {
  if (total === 1) return colors.ink;
  return colors.series[index % colors.series.length] ?? colors.inkMuted;
}

function yDomain(zero: boolean | null): [number | string | ((value: number) => number), number | string | ((value: number) => number)] {
  // Axis extent is layout, not a figure: it only decides where marks sit.
  return zero ? [(min: number) => Math.min(0, min), (max: number) => Math.max(0, max)] : ['auto', 'auto'];
}

function Chart({
  spec,
  records,
  colors,
}: {
  spec: VisualizationSpec;
  records: readonly Record_[];
  colors: ChartColors;
}) {
  const { x, y, band } = spec.encoding;
  const axisTick = { fill: colors.inkFaint, fontSize: 10 };
  const tooltip = (
    <Tooltip
      contentStyle={{
        background: colors.surface,
        border: `1px solid ${colors.hairline}`,
        borderRadius: 3,
        fontSize: 12,
        color: colors.ink,
      }}
      formatter={(value: unknown) =>
        Array.isArray(value)
          ? value.map((part) => (typeof part === 'number' ? formatNumber(part) : String(part))).join(' – ')
          : typeof value === 'number'
            ? formatNumber(value)
            : String(value)
      }
    />
  );
  const grid = <CartesianGrid stroke={colors.hairline} strokeDasharray="2 5" vertical={false} />;
  const yAxis = (
    <YAxis
      tick={axisTick}
      tickFormatter={(value: number) => formatCompact(value)}
      axisLine={false}
      tickLine={false}
      width={52}
      domain={yDomain(y.zero_baseline)}
    />
  );
  const xAxis = (
    <XAxis
      dataKey="x"
      tick={axisTick}
      axisLine={{ stroke: colors.hairlineStrong }}
      tickLine={false}
      minTickGap={16}
    />
  );
  const attention = (emphasis: 'normal' | 'attention') =>
    emphasis === 'attention' ? colors.accent : colors.inkFaint;

  if (spec.kind === 'scatter') {
    const points = records
      .map((record) => ({ x: numberAt(record, x.column), y: numberAt(record, y.column) }))
      .filter((point): point is { x: number; y: number } => point.x !== null && point.y !== null);
    return (
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={colors.hairline} strokeDasharray="2 5" />
          <XAxis type="number" dataKey="x" name={x.label} tick={axisTick} tickFormatter={(value: number) => formatCompact(value)} />
          <YAxis type="number" dataKey="y" name={y.label} tick={axisTick} tickFormatter={(value: number) => formatCompact(value)} width={52} />
          {tooltip}
          <Scatter data={points} fill={colors.inkMuted} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  if (spec.kind === 'forecast_fan' || spec.kind === 'range_band') {
    // The interval is always drawn (VZ-5); a single point is a range, never a
    // line (VZ-6), so range_band draws bars for the band and a dot for y.
    const rows: Row[] = records.map((record) => {
      const low = band ? numberAt(record, band.lower_column) : null;
      const high = band ? numberAt(record, band.upper_column) : null;
      return {
        x: textAt(record, x.column),
        y: numberAt(record, y.column),
        band: low !== null && high !== null ? ([low, high] as const) : null,
      };
    });
    const bandLabel = band?.label ?? 'Interval';
    return (
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
          {grid}
          {xAxis}
          {yAxis}
          {tooltip}
          <Legend wrapperStyle={{ fontSize: 11, color: colors.inkMuted }} />
          {spec.kind === 'forecast_fan' ? (
            <>
              <Area
                dataKey="band"
                name={bandLabel}
                stroke="none"
                fill={colors.series[1]}
                fillOpacity={0.45}
                isAnimationActive={false}
              />
              <Line dataKey="y" name={y.label} stroke={colors.ink} strokeWidth={1.5} dot={{ r: 2.5 }} isAnimationActive={false} />
            </>
          ) : (
            <>
              <Bar dataKey="band" name={bandLabel} fill={colors.series[1]} fillOpacity={0.6} barSize={28} isAnimationActive={false} />
              <Line dataKey="y" name={y.label} stroke="none" dot={{ r: 5, fill: colors.ink }} isAnimationActive={false} />
            </>
          )}
          {spec.annotations.map((note, index) =>
            note.kind === 'line' && note.at.x && rows.some((row) => row.x === note.at.x) ? (
              <ReferenceLine key={index} x={note.at.x} stroke={attention(note.emphasis)} strokeDasharray="3 3" />
            ) : null,
          )}
        </ComposedChart>
      </ResponsiveContainer>
    );
  }

  const { rows, keys } = pivot(spec, records);

  if (spec.kind === 'line') {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
          {grid}
          {xAxis}
          {yAxis}
          {tooltip}
          {keys.length > 1 ? <Legend wrapperStyle={{ fontSize: 11, color: colors.inkMuted }} /> : null}
          {keys.map((key, index) => (
            <Line
              key={key}
              dataKey={key}
              name={key === UNSPLIT ? y.label : key}
              stroke={seriesColour(colors, index, keys.length)}
              strokeWidth={1.5}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
          {spec.annotations.map((note, index) => {
            if (note.kind !== 'point' || !note.at.x) return null;
            const row = rows.find((candidate) => candidate.x === note.at.x);
            // The dot sits on the backend's own cell for that x (VZ-2).
            const value = note.at.y ?? (row ? row[keys[0] ?? UNSPLIT] : null);
            return typeof value === 'number' ? (
              <ReferenceDot
                key={index}
                x={note.at.x}
                y={value}
                r={5}
                fill={colors.surface}
                stroke={attention(note.emphasis)}
                strokeWidth={2}
              />
            ) : null;
          })}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // bar, grouped_bar, waterfall (as contributions from zero)
  const signed = spec.kind === 'waterfall' || keys.length === 1;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
        {grid}
        {xAxis}
        {yAxis}
        {tooltip}
        <ReferenceLine y={0} stroke={colors.hairlineStrong} />
        {keys.length > 1 ? <Legend wrapperStyle={{ fontSize: 11, color: colors.inkMuted }} /> : null}
        {keys.map((key, index) => (
          <Bar
            key={key}
            dataKey={key}
            name={key === UNSPLIT ? y.label : key}
            fill={seriesColour(colors, index, keys.length)}
            maxBarSize={36}
            isAnimationActive={false}
          >
            {signed
              ? rows.map((row, rowIndex) => {
                  const value = row[key];
                  // Sign is a property of the stated value: sage up, terracotta down.
                  const fill =
                    typeof value === 'number' && value < 0 ? colors.terracotta : colors.sage;
                  return <Cell key={rowIndex} fill={fill} />;
                })
              : null}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
