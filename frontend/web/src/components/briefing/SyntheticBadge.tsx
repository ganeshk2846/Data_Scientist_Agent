import { FlaskConical } from 'lucide-react';

/**
 * Shown on every answer that read a generated (synthetic) table (V2-SYN-4,
 * build-plan 5.11). Driven by the backend's own synthetic caveat; legible at
 * AA in both themes because it is ink on the sunken ground, not a colour.
 */
export function SyntheticBadge({ detail }: { detail: string }) {
  return (
    <span
      title={detail}
      className="inline-flex items-center gap-1.5 rounded-sm border border-hairline-strong bg-sunken px-2 py-0.5 text-micro uppercase text-ink-muted"
      data-testid="synthetic-badge"
    >
      <FlaskConical size={11} strokeWidth={1.5} aria-hidden />
      Synthetic data
      <span className="sr-only">: {detail}</span>
    </span>
  );
}
