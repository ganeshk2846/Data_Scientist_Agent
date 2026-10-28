import { Clipboard, Check, MonitorPlay, Printer } from 'lucide-react';
import { useCallback, useState } from 'react';

import { cx } from '@/lib/cx';
import { briefingToMarkdown } from '@/lib/exportBriefing';
import type { AnswerEnvelope } from '@/types/envelope';

/**
 * Export and presentation controls.
 *
 * "Download PDF" is the browser's own print dialogue driven against the print
 * stylesheet in `index.css` — the viewer's "Save as PDF" is the most reliable
 * PDF route there is, and it needs no library and no sandbox exception.
 */
export function BriefingToolbar({
  envelope,
  question,
  onPresent,
}: {
  envelope: AnswerEnvelope;
  question: string | null;
  onPresent: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const copyBriefing = useCallback(() => {
    const markdown = briefingToMarkdown(envelope, question);
    void navigator.clipboard.writeText(markdown).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 2_200);
      },
      () => setCopied(false),
    );
  }, [envelope, question]);

  const button = cx(
    'inline-flex items-center gap-2 rounded-[3px] border px-3 py-1.5',
    'text-[0.75rem] transition-colors duration-micro ease-editorial',
    'border-hairline text-ink-muted hover:border-gold hover:text-ink',
  );

  return (
    <div data-print="hide" className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={copyBriefing}
        className={cx(button, copied && 'border-gold text-gold-ink')}
        aria-label={copied ? 'Copied the briefing as Markdown' : 'Copy as briefing'}
      >
        <span className="relative grid h-3.5 w-3.5 place-items-center">
          <Clipboard
            size={12}
            strokeWidth={1.75}
            aria-hidden
            className={cx(
              'absolute transition-all duration-200 ease-editorial',
              copied ? 'scale-75 opacity-0' : 'scale-100 opacity-100',
            )}
          />
          <Check
            size={12}
            strokeWidth={2.5}
            aria-hidden
            className={cx(
              'absolute transition-all duration-300 ease-editorial',
              copied ? 'scale-100 opacity-100' : 'scale-50 opacity-0',
            )}
          />
        </span>
        {copied ? 'Copied' : 'Copy as briefing'}
      </button>

      <button
        type="button"
        onClick={() => window.print()}
        className={button}
        aria-label="Download PDF"
      >
        <Printer size={12} strokeWidth={1.75} aria-hidden />
        Download PDF
      </button>

      <button
        type="button"
        onClick={onPresent}
        className={button}
        aria-label="Present — presentation mode"
        title="Presentation mode (P)"
      >
        <MonitorPlay size={12} strokeWidth={1.75} aria-hidden />
        Present
      </button>
    </div>
  );
}
