import { BarChart3, ImageDown, Table2 } from 'lucide-react';
import { useCallback, useRef, useState, type ReactNode } from 'react';

import { useToast } from '@/components/ui/Toast';
import { cx } from '@/lib/cx';
import { downloadBlob, svgToPng } from '@/lib/download';

/**
 * The frame every chart sits in.
 *
 * Two affordances, and the reason for each. **View as table** is the honest
 * alternative to a chart: a reader who needs the figure rather than the shape
 * should not have to read it off an axis, and the table is the same values the
 * chart was drawn from. **Download PNG** rasterises the chart that is actually
 * on screen — Recharts renders real SVG, so the file is the drawing, at 2× and
 * on the page's own ground rather than on transparency.
 *
 * The toggle is a segmented pair rather than a link, because the two views are
 * peers: neither is the "real" one.
 */
export function ChartFrame({
  children,
  table,
  filename,
  /** Named in the accessible labels, so the controls say what they act on. */
  subject,
}: {
  children: ReactNode;
  /** The same values, as rows. Omit and the table toggle is not offered. */
  table?: ReactNode;
  filename: string;
  subject: string;
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart');
  const [saving, setSaving] = useState(false);
  const host = useRef<HTMLDivElement | null>(null);
  const toast = useToast();

  const download = useCallback(async () => {
    const svg = host.current?.querySelector('svg');
    if (!(svg instanceof SVGSVGElement)) {
      toast.fault('There is no drawn chart to save.');
      return;
    }
    setSaving(true);
    try {
      // The page's own ground, so a dark-mode chart is saved on onyx and a
      // light-mode one on ivory — a transparent PNG would be unreadable in
      // whichever viewer the reader opens it in.
      const background = window.getComputedStyle(document.body).backgroundColor;
      const blob = await svgToPng(svg, { background: background || '#ffffff' });
      downloadBlob(blob, filename);
      toast.done('Chart saved', filename);
    } catch {
      toast.fault('The chart could not be saved as a PNG.');
    } finally {
      setSaving(false);
    }
  }, [filename, toast]);

  return (
    <figure className="m-0">
      <div
        className="mb-4 flex flex-wrap items-center justify-end gap-2"
        data-print="hide"
      >
        {table ? (
          <div
            role="radiogroup"
            aria-label={`How to show ${subject}`}
            className="inline-flex rounded-sm border border-hairline bg-sunken p-0.5"
          >
            {(
              [
                ['chart', 'Chart', BarChart3],
                ['table', 'Table', Table2],
              ] as const
            ).map(([value, label, Icon]) => {
              const active = view === value;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setView(value)}
                  className={cx(
                    'inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1',
                    'text-[0.75rem] transition-colors duration-hover ease-editorial',
                    active
                      ? 'bg-surface text-ink shadow-soft'
                      : 'text-ink-faint hover:text-ink-muted',
                  )}
                >
                  <Icon size={13} strokeWidth={1.5} aria-hidden />
                  {label}
                </button>
              );
            })}
          </div>
        ) : null}

        <button
          type="button"
          onClick={() => void download()}
          disabled={saving || view === 'table'}
          className={cx(
            'inline-flex items-center gap-2 rounded-sm border border-hairline px-2.5 py-1.5',
            'text-[0.75rem] text-ink-muted transition-colors duration-hover ease-editorial',
            'hover:border-hairline-strong hover:text-ink',
            'disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-hairline',
          )}
        >
          <ImageDown size={13} strokeWidth={1.5} aria-hidden />
          {saving ? 'Saving…' : 'Download PNG'}
          <span className="sr-only"> of {subject}</span>
        </button>
      </div>

      {/* Both views stay mounted so toggling never re-animates the chart, and
          the hidden one is taken out of the a11y tree with `hidden`. */}
      <div ref={host} hidden={view !== 'chart'}>
        {children}
      </div>
      {table ? <div hidden={view !== 'table'}>{table}</div> : null}
    </figure>
  );
}
