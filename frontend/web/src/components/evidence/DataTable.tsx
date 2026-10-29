import { ArrowDown, ArrowUp, Download, Search } from 'lucide-react';
import { useId, useMemo, useState } from 'react';

import { useToast } from '@/components/ui/Toast';
import { cx } from '@/lib/cx';
import { downloadCsv, toCsv } from '@/lib/download';
import { formatNumber } from '@/lib/format';

/**
 * The result table: sortable, searchable, exportable.
 *
 * SAFE-8: sorting *reorders* the rows the backend returned and searching
 * *hides* some of them. Neither changes a value, and nothing is aggregated —
 * there is no total row, no computed column and no row count of our own. The
 * authoritative count is the envelope's `row_count`, printed as such, with the
 * visible count beside it when a filter is on.
 *
 * Numeric columns are detected from the data rather than from the declared
 * type, because the governed compiler reports its measures as the bare type
 * "number", which matches no SQL type name (CLAUDE.md gap 15).
 */

export interface DataColumn {
  name: string;
  /** The declared type, shown as a small caption. Optional. */
  type?: string;
}

interface DataTableProps {
  columns: readonly DataColumn[];
  rows: readonly (readonly unknown[])[];
  /** Names the scroll region, so a keyboard user knows what they are in. */
  label: string;
  /** The envelope's own authoritative count. */
  rowCount?: number;
  truncated?: boolean;
  /** When set, the Export CSV control appears and writes this filename. */
  csvFilename?: string;
  /** Extra provenance for the footer rail — a query id, usually. */
  footnote?: string;
  /** Below this many rows, the toolbar is noise and is not drawn. */
  toolbarFrom?: number;
  maxRows?: number;
  /**
   * Stamped on the wrapper as `data-testid`, so a harness can name *which*
   * table it means. A page often shows several — a lookup's rows and a chart's
   * "view as table" are both this component — and an unscoped `tbody tr`
   * sweeps up all of them.
   */
  testId?: string;
}

type Direction = 'asc' | 'desc';

function isNumericColumn(
  rows: readonly (readonly unknown[])[],
  index: number,
): boolean {
  for (const row of rows) {
    const value = row[index];
    if (value === null || value === undefined) continue;
    return typeof value === 'number';
  }
  return false;
}

/** Nulls last in both directions: an empty cell is never "the smallest". */
function compare(a: unknown, b: unknown): number {
  const aEmpty = a === null || a === undefined;
  const bEmpty = b === null || b === undefined;
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), 'en', { numeric: true });
}

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

export function DataTable({
  columns,
  rows,
  label,
  rowCount,
  truncated = false,
  csvFilename,
  footnote,
  toolbarFrom = 6,
  maxRows = 50,
  testId,
}: DataTableProps) {
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ index: number; direction: Direction } | null>(null);
  const searchId = useId();
  const toast = useToast();

  const numeric = useMemo(
    () => columns.map((_, index) => isNumericColumn(rows, index)),
    [columns, rows],
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) =>
      row.some((cell) => String(cell ?? '').toLowerCase().includes(needle)),
    );
  }, [query, rows]);

  const sorted = useMemo(() => {
    if (!sort) return filtered;
    const next = [...filtered];
    next.sort((a, b) => {
      const result = compare(a[sort.index], b[sort.index]);
      return sort.direction === 'asc' ? result : -result;
    });
    return next;
  }, [filtered, sort]);

  const visible = sorted.slice(0, maxRows);
  const hidden = sorted.length - visible.length;
  const filtering = query.trim().length > 0;
  const showToolbar = rows.length >= toolbarFrom;

  if (columns.length === 0) {
    return <p className="text-small text-ink-muted">This query returned no columns.</p>;
  }

  const onExport = () => {
    if (!csvFilename) return;
    // Exactly what is on screen, in the backend's own column order.
    downloadCsv(csvFilename, toCsv(columns, sorted));
    toast.done('Rows exported', csvFilename);
  };

  return (
    <div data-testid={testId}>
      {showToolbar || csvFilename ? (
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2" data-print="hide">
          {showToolbar ? (
            <div className="relative min-w-0 flex-1 sm:max-w-[16rem]">
              <Search
                size={13}
                strokeWidth={1.5}
                aria-hidden
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint"
              />
              <input
                id={searchId}
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search rows"
                aria-label={`Search ${label}`}
                className={cx(
                  'w-full rounded-sm border border-hairline bg-sunken py-1.5 pl-8 pr-2.5',
                  'text-[0.8125rem] leading-5 text-ink placeholder:text-ink-faint',
                  'transition-colors duration-hover ease-editorial hover:border-hairline-strong',
                )}
              />
            </div>
          ) : null}

          {csvFilename ? (
            <button
              type="button"
              onClick={onExport}
              className={cx(
                'ml-auto inline-flex items-center gap-2 rounded-sm border border-hairline px-2.5 py-1.5',
                'text-[0.75rem] text-ink-muted transition-colors duration-hover ease-editorial',
                'hover:border-hairline-strong hover:text-ink',
              )}
            >
              <Download size={13} strokeWidth={1.5} aria-hidden />
              Export CSV
            </button>
          ) : null}
        </div>
      ) : null}

      {/* Wide and tall results scroll inside their own container, never the
          page. tabIndex makes the scroll region reachable, so a keyboard user
          can actually scroll a long result. */}
      <div
        data-print="flow"
        tabIndex={0}
        role="region"
        aria-label={label}
        className="-mx-1 max-h-[22rem] overflow-auto px-1"
      >
        <table className="w-full min-w-full border-collapse text-small">
          <thead>
            <tr className="sticky top-0 z-10 border-b border-hairline-strong bg-surface">
              {columns.map((column, index) => {
                const active = sort?.index === index;
                return (
                  <th
                    key={column.name}
                    scope="col"
                    aria-sort={
                      active
                        ? sort.direction === 'asc'
                          ? 'ascending'
                          : 'descending'
                        : 'none'
                    }
                    className={cx(
                      'whitespace-nowrap p-0 text-micro font-medium uppercase',
                      numeric[index] ? 'text-right' : 'text-left',
                    )}
                  >
                    <button
                      type="button"
                      onClick={() =>
                        setSort((current) =>
                          current?.index === index
                            ? current.direction === 'asc'
                              ? { index, direction: 'desc' }
                              : null
                            : { index, direction: 'asc' },
                        )
                      }
                      className={cx(
                        'group flex w-full items-baseline gap-1.5 px-3 py-2.5 uppercase',
                        'transition-colors duration-hover ease-editorial',
                        numeric[index] ? 'justify-end' : 'justify-start',
                        active ? 'text-ink' : 'text-ink-faint hover:text-ink-muted',
                      )}
                    >
                      <span>{column.name}</span>
                      {column.type ? (
                        <span className="normal-case tracking-normal text-ink-faint/70">
                          {column.type}
                        </span>
                      ) : null}
                      {/* The sort mark holds its space, so toggling sort never
                          shifts a column by a few pixels. */}
                      <span aria-hidden className="inline-flex w-3 shrink-0 justify-center">
                        {active ? (
                          sort.direction === 'asc' ? (
                            <ArrowUp size={10} strokeWidth={1.5} />
                          ) : (
                            <ArrowDown size={10} strokeWidth={1.5} />
                          )
                        ) : (
                          <ArrowUp
                            size={10}
                            strokeWidth={1.5}
                            className="opacity-0 transition-opacity duration-hover group-hover:opacity-50"
                          />
                        )}
                      </span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, rowIndex) => (
              <tr
                key={rowIndex}
                className="border-b border-hairline last:border-0 hover:bg-[rgb(var(--c-hairline)/0.4)]"
              >
                {columns.map((column, index) => (
                  <td
                    key={column.name}
                    className={cx(
                      'whitespace-nowrap px-3 py-2.5 text-ink',
                      numeric[index] ? 'text-right' : 'text-left',
                    )}
                  >
                    <Cell value={row[index]} />
                  </td>
                ))}
              </tr>
            ))}
            {visible.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-3 py-8 text-center text-[0.8125rem] text-ink-faint"
                >
                  No row matches “{query}”.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[0.6875rem] text-ink-faint">
        {rowCount !== undefined ? (
          <span className="tabular-nums">
            {formatNumber(rowCount)} row{rowCount === 1 ? '' : 's'}
          </span>
        ) : null}
        {filtering ? (
          <span className="tabular-nums">
            {formatNumber(sorted.length)} matching
          </span>
        ) : null}
        {hidden > 0 ? (
          <span className="tabular-nums">{formatNumber(hidden)} more not shown</span>
        ) : null}
        {truncated ? (
          <span className="text-terracotta">truncated by the row bound</span>
        ) : null}
        {footnote ? <span className="font-mono">{footnote}</span> : null}
      </div>
    </div>
  );
}
