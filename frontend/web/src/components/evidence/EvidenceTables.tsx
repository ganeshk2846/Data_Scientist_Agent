import { DataTable } from './DataTable';
import { safeFilename } from '@/lib/download';
import { sortDrivers, type SeriesPoint } from '@/lib/evidence';
import type { AnomalyResult, DriverResult } from '@/types/envelope';

/**
 * The tabular view of each chart.
 *
 * These are the chart's own inputs, written out as rows — not a summary of
 * them. The series table holds the points the chart plots; the anomaly table
 * holds the eight fields `AnomalyResult` states; the driver table holds one row
 * per `DriverContribution` with every field that contract carries. Nothing is
 * totalled, ranked by us, or converted.
 */

export function SeriesTable({
  series,
  anomaly,
  subject,
}: {
  series: readonly SeriesPoint[];
  anomaly: AnomalyResult;
  subject: string;
}) {
  if (series.length > 0) {
    return (
      <DataTable
        columns={[{ name: 'period' }, { name: 'value' }]}
        rows={series.map((point) => [point.label, point.value])}
        label={`Plotted points for ${subject}`}
        rowCount={series.length}
        csvFilename={safeFilename([subject, 'series'], 'csv')}
        footnote={`window ${anomaly.window}`}
      />
    );
  }

  // No series: the chart fell back to the range bar, so the table is the
  // analyst's own stated fields.
  return (
    <DataTable
      columns={[{ name: 'field' }, { name: 'value' }]}
      rows={[
        ['window', anomaly.window],
        ['verdict', anomaly.verdict],
        ['actual', anomaly.actual],
        ['expected', anomaly.expected],
        ['expected_range_low', anomaly.expected_range[0]],
        ['expected_range_high', anomaly.expected_range[1]],
        ['deviation_pct', anomaly.deviation_pct],
        ['robust_score', anomaly.robust_score],
        ['threshold', anomaly.threshold],
        ['persistence', anomaly.persistence],
        ['baseline_kind', anomaly.baseline_kind],
      ]}
      label={`Anomaly result for ${subject}`}
      csvFilename={safeFilename([subject, 'anomaly'], 'csv')}
      toolbarFrom={999}
    />
  );
}

export function DriverTable({
  result,
  subject,
}: {
  result: DriverResult;
  subject: string;
}) {
  return (
    <DataTable
      columns={[
        { name: 'dimension' },
        { name: 'value' },
        { name: 'contribution' },
        { name: 'share' },
        { name: 'interval_low' },
        { name: 'interval_high' },
        { name: 'sample_size' },
        { name: 'grade' },
        { name: 'unstable' },
      ]}
      // The same order the bars are drawn in, which is the contract's own
      // contributions sorted by magnitude — see `sortDrivers`.
      rows={sortDrivers(result).map((driver) => [
        driver.dimension,
        driver.value,
        driver.contribution,
        driver.share,
        driver.interval[0],
        driver.interval[1],
        driver.sample_size,
        driver.grade,
        driver.unstable,
      ])}
      label={`Driver contributions for ${subject}`}
      rowCount={result.drivers.length}
      csvFilename={safeFilename([subject, 'drivers'], 'csv')}
      footnote={`${result.current_period} vs ${result.comparison_period}`}
    />
  );
}
