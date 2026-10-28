/**
 * Number and time formatting. Every figure this product shows is tabular, so
 * these helpers never emit a character that breaks column alignment.
 */

const compact = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 1,
});

/** Full precision with thousands separators: 12,480. */
export function formatNumber(value: number, fractionDigits?: number): string {
  if (!Number.isFinite(value)) return '—';
  const digits = fractionDigits ?? (Number.isInteger(value) ? 0 : 2);
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** For headline figures where width matters: 1.2M. */
export function formatCompact(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return compact.format(value);
}

/** Signed, for deltas and contributions: +1,204 / −318. */
export function formatSigned(value: number, fractionDigits?: number): string {
  if (!Number.isFinite(value)) return '—';
  const sign = value < 0 ? '−' : '+';
  return `${sign}${formatNumber(Math.abs(value), fractionDigits)}`;
}

/** 12.4% — always one decimal, always signed when asked. */
export function formatPercent(value: number, signed = false): string {
  if (!Number.isFinite(value)) return '—';
  const body = `${Math.abs(value).toFixed(1)}%`;
  if (!signed) return value < 0 ? `−${body}` : body;
  return `${value < 0 ? '−' : '+'}${body}`;
}

/** 0.94 confidence as 94%. */
export function formatConfidence(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return `${Math.round(value * 100)}%`;
}

/** 412 ms / 1.84 s / 2 m 04 s. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes} m ${String(seconds).padStart(2, '0')} s`;
}

/** "just now", "4 min ago", "11:42" past an hour. */
export function formatRelativeTime(timestamp: number, now = Date.now()): string {
  const delta = Math.max(0, now - timestamp);
  if (delta < 45_000) return 'just now';
  const minutes = Math.round(delta / 60_000);
  if (minutes < 60) return `${minutes} min ago`;
  return new Date(timestamp).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/**
 * `scope.window` arrives as an ISO half-open interval, "2018-08-01/2018-09-01".
 * Render it as a human period, with the exclusive end pulled back a day.
 */
export function formatWindow(window: string | null): string | null {
  if (!window) return null;
  const parts = window.split('/');
  if (parts.length !== 2) return window;
  const [rawStart, rawEnd] = parts as [string, string];
  const start = new Date(`${rawStart}T00:00:00Z`);
  const end = new Date(`${rawEnd}T00:00:00Z`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return window;
  end.setUTCDate(end.getUTCDate() - 1);
  const month = (date: Date) =>
    date.toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
  const full = (date: Date) =>
    date.toLocaleDateString('en-US', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      timeZone: 'UTC',
    });
  // A whole calendar month reads better as "Aug 2018" than as a date range.
  const wholeMonth =
    start.getUTCDate() === 1 &&
    end.getUTCMonth() === start.getUTCMonth() &&
    end.getUTCFullYear() === start.getUTCFullYear() &&
    end.getUTCDate() >= 28;
  if (wholeMonth) return month(start);
  return `${full(start)} – ${full(end)}`;
}

/** Shortens a run id for chrome: "a4f19c2e…". */
export function shortRunId(runId: string): string {
  return runId.length <= 10 ? runId : `${runId.slice(0, 8)}…`;
}

/** snake_case and kebab-case to Sentence case, for contract literals. */
export function humanise(value: string): string {
  const spaced = value.replace(/[_-]+/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
