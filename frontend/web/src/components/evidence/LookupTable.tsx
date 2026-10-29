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
      rowCount={output.row_count}
      truncated={output.truncated}
      csvFilename={safeFilename([subject ?? null, output.query_id], 'csv')}
      footnote={output.query_id}
    />
  );
}
