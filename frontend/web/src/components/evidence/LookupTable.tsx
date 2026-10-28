import { formatNumber } from '@/lib/format';
import { cx } from '@/lib/cx';
import type { LookupOutput } from '@/types/envelope';

/** Numbers right-align and stay tabular; everything else reads left. */
function Cell({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="text-ink-faint">—</span>;
  }
  if (typeof value === 'number') {
    return <span className="tabular-nums">{formatNumber(value)}</span>;
  }
  if (typeof value === 'boolean') return <span>{value ? 'true' : 'false'}</span>;
  return <span>{String(value)}</span>;
}

function isNumericColumn(rows: LookupOutput['rows'], index: number): boolean {
  for (const row of rows) {
    const value = row[index];
    if (value === null || value === undefined) continue;
    return typeof value === 'number';
  }
  return false;
}

const MAX_ROWS = 50;

export function LookupTable({ output }: { output: LookupOutput }) {
  const rows = output.rows.slice(0, MAX_ROWS);
  const hidden = output.rows.length - rows.length;

  if (output.columns.length === 0) {
    return <p className="text-small text-ink-muted">This query returned no columns.</p>;
  }

  return (
    <div>
      {/* Wide and tall results scroll inside their own container, never the
          page — a 23-row series must not bury the chart beneath it. */}
      {/* tabIndex makes the scroll region reachable, so a keyboard user can
          actually scroll a long result; the label says what they are in. */}
      <div
        data-print="flow"
        tabIndex={0}
        role="region"
        aria-label={`Result rows for ${output.query_id}`}
        className="-mx-1 max-h-[22rem] overflow-auto px-1"
      >
        <table className="w-full min-w-full border-collapse text-small">
          <thead>
            <tr className="sticky top-0 z-10 border-b border-hairline-strong bg-surface">
              {output.columns.map((column, index) => (
                <th
                  key={column.name}
                  scope="col"
                  className={cx(
                    'whitespace-nowrap px-3 py-2.5 text-micro font-medium uppercase text-ink-faint',
                    isNumericColumn(output.rows, index) ? 'text-right' : 'text-left',
                  )}
                >
                  {column.name}
                  <span className="ml-2 normal-case tracking-normal text-ink-faint/70">
                    {column.type}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr
                key={rowIndex}
                className="border-b border-hairline last:border-0 hover:bg-[var(--c-gold-wash)]"
              >
                {output.columns.map((column, index) => (
                  <td
                    key={column.name}
                    className={cx(
                      'whitespace-nowrap px-3 py-2.5 text-ink',
                      isNumericColumn(output.rows, index) ? 'text-right' : 'text-left',
                    )}
                  >
                    <Cell value={row[index]} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[0.6875rem] text-ink-faint">
        <span className="tabular-nums">
          {formatNumber(output.row_count)} row{output.row_count === 1 ? '' : 's'}
        </span>
        {hidden > 0 ? (
          <span className="tabular-nums">{formatNumber(hidden)} more not shown</span>
        ) : null}
        {output.truncated ? (
          <span className="text-terracotta">truncated by the row bound</span>
        ) : null}
        <span className="font-mono">{output.query_id}</span>
      </div>
    </div>
  );
}
