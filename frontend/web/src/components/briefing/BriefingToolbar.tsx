import {
  Check,
  Clipboard,
  ListTree,
  MonitorPlay,
  Pin,
  Printer,
  Star,
} from 'lucide-react';
import { useCallback, useState, type ReactNode } from 'react';

import { useToast } from '@/components/ui/Toast';
import { cx } from '@/lib/cx';
import { briefingToMarkdown } from '@/lib/exportBriefing';
import type { AnswerEnvelope } from '@/types/envelope';

/**
 * The briefing's actions.
 *
 * Every control carries a text label beside its icon. An icon-only toolbar
 * saves a few millimetres and costs the reader a guess, and this is the one
 * row in the product where a wrong guess throws away work — a stray Print, a
 * pin they did not mean. The labels also give every button an accessible name
 * from its own content, so there is no `aria-label` to drift out of step.
 *
 * "Download PDF" is the browser's own print dialogue driven against the print
 * stylesheet in `index.css` — the viewer's "Save as PDF" is the most reliable
 * PDF route there is, and it needs no library and no sandbox exception.
 */

function ToolbarButton({
  children,
  onClick,
  active = false,
  disabled = false,
  title,
}: {
  children: ReactNode;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cx(
        'inline-flex items-center gap-2 rounded-sm border px-2.5 py-1.5',
        'text-[0.75rem] leading-4',
        // One transition, one easing, and a press that actually depresses.
        'transition-[color,border-color,background-color,transform] duration-hover ease-editorial',
        'active:translate-y-px',
        'disabled:cursor-not-allowed disabled:opacity-45 disabled:active:translate-y-0',
        active
          ? 'border-accent bg-[var(--c-accent-wash)] text-accent-ink'
          : 'border-hairline text-ink-muted hover:border-hairline-strong hover:text-ink',
      )}
    >
      {children}
    </button>
  );
}

export function BriefingToolbar({
  envelope,
  question,
  starred,
  pinned,
  canPin,
  onToggleStar,
  onPin,
  onInspect,
  onPresent,
}: {
  envelope: AnswerEnvelope;
  question: string | null;
  starred: boolean;
  pinned: boolean;
  /** False when the envelope states no single headline figure to pin. */
  canPin: boolean;
  onToggleStar: () => void;
  onPin: () => void;
  onInspect: () => void;
  onPresent: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const toast = useToast();

  const copyBriefing = useCallback(() => {
    const markdown = briefingToMarkdown(envelope, question);
    void navigator.clipboard.writeText(markdown).then(
      () => {
        setCopied(true);
        toast.done('Briefing copied as Markdown');
        window.setTimeout(() => setCopied(false), 2_200);
      },
      () => {
        setCopied(false);
        toast.fault('The clipboard refused the copy.');
      },
    );
  }, [envelope, question, toast]);

  return (
    <div data-print="hide" className="flex flex-wrap items-center gap-2">
      <ToolbarButton
        onClick={onToggleStar}
        active={starred}
        title={starred ? 'Remove the star (S)' : 'Star this answer (S)'}
      >
        <Star
          size={13}
          strokeWidth={1.5}
          aria-hidden
          className={starred ? 'fill-current' : undefined}
        />
        {starred ? 'Starred' : 'Star'}
      </ToolbarButton>

      <ToolbarButton
        onClick={onPin}
        active={pinned}
        disabled={!canPin}
        title={
          canPin
            ? pinned
              ? 'Already on the pinboard'
              : 'Pin the headline figure (⇧P)'
            : 'This answer states no single headline figure'
        }
      >
        <Pin size={13} strokeWidth={1.5} aria-hidden />
        {pinned ? 'Pinned' : 'Pin figure'}
      </ToolbarButton>

      <ToolbarButton onClick={copyBriefing} active={copied}>
        {/* The tick draws itself on; a swap would feel like a glitch. */}
        <span className="relative grid h-3.5 w-3.5 place-items-center">
          <Clipboard
            size={13}
            strokeWidth={1.5}
            aria-hidden
            className={cx(
              'absolute transition-all duration-200 ease-editorial',
              copied ? 'scale-75 opacity-0' : 'scale-100 opacity-100',
            )}
          />
          <Check
            size={13}
            strokeWidth={1.5}
            aria-hidden
            className={cx(
              'absolute transition-all duration-micro ease-editorial',
              copied ? 'scale-100 opacity-100' : 'scale-50 opacity-0',
            )}
          />
        </span>
        {copied ? 'Copied' : 'Copy briefing'}
      </ToolbarButton>

      <ToolbarButton onClick={onInspect} title="Run inspector (I)">
        <ListTree size={13} strokeWidth={1.5} aria-hidden />
        Inspect run
      </ToolbarButton>

      <ToolbarButton onClick={() => window.print()} title="Opens the print dialogue">
        <Printer size={13} strokeWidth={1.5} aria-hidden />
        Download PDF
      </ToolbarButton>

      <ToolbarButton onClick={onPresent} title="Presentation mode (P)">
        <MonitorPlay size={13} strokeWidth={1.5} aria-hidden />
        Present
      </ToolbarButton>
    </div>
  );
}
