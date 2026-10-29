/**
 * Export: CSV of the rows the backend returned, and PNG of a chart as drawn.
 *
 * SAFE-8: `toCsv` transcribes. Every cell is the value the envelope carried,
 * written out with no formatting applied — a CSV is read by a spreadsheet, and
 * a thousands separator or an en-dash for null would corrupt it. Nothing is
 * totalled, and no column is added.
 */

/** The line ending RFC 4180 asks for, and Excel insists on. */
const CRLF = String.fromCharCode(13, 10);

/** RFC 4180: quote anything containing a comma, a quote or a newline. */
function field(value: unknown): string {
  if (value === null || value === undefined) return '';
  const text = typeof value === 'number' ? String(value) : String(value);
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

/**
 * The rows exactly as the backend returned them, in the backend's own column
 * order. `rows` may be a sorted or filtered view of what the envelope carried —
 * what the reader is looking at is what they get — but the values are
 * untouched, and no column and no total is added.
 */
export function toCsv(
  columns: readonly { name: string }[],
  rows: readonly (readonly unknown[])[],
): string {
  const lines = [columns.map((column) => field(column.name)).join(',')];
  for (const row of rows) {
    lines.push(columns.map((_, index) => field(row[index])).join(','));
  }
  // A trailing newline, so `cat` and `wc -l` agree with the row count.
  return lines.join(CRLF) + CRLF;
}

/** Hands the browser a file. Revoked on the next tick, once the click is done. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function downloadCsv(filename: string, csv: string): void {
  // The BOM is what makes Excel read UTF-8 instead of the system codepage.
  downloadBlob(new Blob([`﻿${csv}`], { type: 'text/csv;charset=utf-8' }), filename);
}

/** A filename that is safe on every OS and still says what it holds. */
export function safeFilename(parts: readonly (string | null)[], extension: string): string {
  const slug = parts
    .filter((part): part is string => !!part)
    .join('-')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 72);
  return `${slug || 'export'}.${extension}`;
}

/**
 * Rasterises an inline SVG to a PNG at 2× for a retina-sharp file.
 *
 * Recharts renders real SVG, so the chart on screen is the chart in the file.
 * The clone is given the computed stroke and fill colours it inherited from the
 * page — an SVG serialised away from the document loses every CSS variable, and
 * the result would otherwise rasterise black on transparent.
 */
export async function svgToPng(
  svg: SVGSVGElement,
  options: { background: string; scale?: number } = { background: '#ffffff' },
): Promise<Blob> {
  const scale = options.scale ?? 2;
  const rect = svg.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));

  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('width', String(width));
  clone.setAttribute('height', String(height));
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');

  // Inline the resolved paint, so no CSS variable has to survive serialisation.
  const originals = svg.querySelectorAll('*');
  const clones = clone.querySelectorAll('*');
  for (let index = 0; index < originals.length; index += 1) {
    const original = originals[index];
    const copy = clones[index];
    if (!(original instanceof Element) || !(copy instanceof SVGElement)) continue;
    const computed = window.getComputedStyle(original);
    for (const property of ['fill', 'stroke', 'stroke-width', 'opacity', 'font-family', 'font-size', 'font-weight'] as const) {
      const value = computed.getPropertyValue(property);
      if (value) copy.setAttribute(property, value);
    }
  }

  const serialised = new XMLSerializer().serializeToString(clone);
  const source = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(serialised)}`;

  const image = new Image();
  image.width = width;
  image.height = height;
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error('The chart could not be rasterised.'));
    image.src = source;
  });

  const canvas = document.createElement('canvas');
  canvas.width = width * scale;
  canvas.height = height * scale;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('This browser gave us no 2D canvas context.');
  context.fillStyle = options.background;
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('The chart could not be encoded as a PNG.'));
    }, 'image/png');
  });
}
