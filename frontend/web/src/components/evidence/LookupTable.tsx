import { DataTable } from './DataTable';
import { safeFilename } from '@/lib/download';
import type { LookupOutput } from '@/types/envelope';

/**
 * A lookup's result rows.
 *
 * The behaviour — sorting, searching, CSV — lives in `DataTable`, which the
 * chart cards' "view as table" also uses, so a table is a table wherever it
 * appears. This file's job is only to map the lookup contract onto it and to
 * name the export file after the query it came from.
 *
 * It carries `data-testid="lookup-table"`, so a harness can address the main
 * result table on its own. An answered run often renders a chart whose "view
 * as table" is this same component, and an unscoped `tbody tr` reads both at
 * once.
 */
export function LookupTable({
  output,
  /** Used in the CSV filename, so a download says what it holds. */
  subject,
}: {
  output: LookupOutput;
  subject?: string | null;
}) {
  return (
    <DataTable
      columns={output.columns.map((column) => ({
        name: column.name,
        type: column.type,
      }))}
      rows={output.rows}
      label={`Result rows for ${output.query_id}`}
      {...(output.row_count !== null ? { rowCount: output.row_count } : {})}
      truncated={output.truncated}
      csvFilename={safeFilename([subject ?? null, output.query_id], 'csv')}
      footnote={output.query_id}
      testId="lookup-table"
    />
  );
}
