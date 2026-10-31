import { MessageSquarePlus, PlayCircle } from 'lucide-react';
import { useState } from 'react';

import { InterpretedAs } from '@/components/briefing/InterpretedAs';
import { STATUS_LABEL } from '@/components/briefing/StatusBadge';
import { SectionLabel } from '@/components/ui/Card';
import type { HistoryEntry } from '@/hooks/useSession';
import { asV2 } from '@/lib/v2';

/** The rewritten question when the backend read it differently from what was typed. */
export function interpretedText(entry: { question: string; envelope: HistoryEntry['envelope'] }): {
  text: string | null;
  inherited: readonly string[];
} {
  const resolved = asV2(entry.envelope)?.resolved_question ?? null;
  if (!resolved) return { text: null, inherited: [] };
  const effective = resolved.effective_text;
  return {
    text: effective && effective.trim() !== entry.question.trim() ? effective : null,
    inherited: resolved.inherited_fields,
  };
}

const VISIBLE_TURNS = 3;

/**
 * The turns before the current one in this conversation, chat-style: the
 * question, how it was interpreted, and the answer's own conclusion (Track 5,
 * item 3). Follow-ups inherit this context on the backend; "New topic" starts
 * a cold conversation.
 */
export function ConversationThread({
  turns,
  onOpen,
  onNewTopic,
  onReplay,
}: {
  /** Earlier turns, oldest first. */
  turns: readonly HistoryEntry[];
  onOpen: (localId: string) => void;
  onNewTopic: () => void;
  onReplay: (() => void) | null;
}) {
  const [showAll, setShowAll] = useState(false);
  // The most recent turns carry the context; older ones fold away.
  const hidden = showAll ? 0 : Math.max(0, turns.length - VISIBLE_TURNS);
  const visible = turns.slice(hidden);
  return (
    <section data-print="hide" data-testid="conversation-thread">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionLabel>
          {turns.length > 0 ? `This conversation · ${turns.length} earlier ${turns.length === 1 ? 'turn' : 'turns'}` : 'This conversation'}
        </SectionLabel>
        <div className="flex flex-wrap gap-2">
          {onReplay ? (
            <button
              type="button"
              onClick={onReplay}
              className="inline-flex items-center gap-1.5 rounded-sm border border-hairline px-2.5 py-1 text-[0.75rem] text-ink-muted transition-colors duration-hover hover:border-hairline-strong hover:text-ink"
            >
              <PlayCircle size={13} strokeWidth={1.5} aria-hidden />
              Replay
            </button>
          ) : null}
          <button
            type="button"
            onClick={onNewTopic}
            className="inline-flex items-center gap-1.5 rounded-sm border border-hairline px-2.5 py-1 text-[0.75rem] text-ink-muted transition-colors duration-hover hover:border-hairline-strong hover:text-ink"
            data-testid="new-topic"
          >
            <MessageSquarePlus size={13} strokeWidth={1.5} aria-hidden />
            New topic
          </button>
        </div>
      </div>
      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="mt-3 text-[0.75rem] text-ink-faint underline-offset-2 hover:text-ink-muted hover:underline"
        >
          Show {hidden} earlier {hidden === 1 ? 'turn' : 'turns'}
        </button>
      ) : null}
      {turns.length > 0 ? (
        <ol className="mt-4 space-y-3 border-l border-hairline pl-4">
          {visible.map((turn) => {
            const read = interpretedText(turn);
            return (
              <li key={turn.localId}>
                <button
                  type="button"
                  onClick={() => onOpen(turn.localId)}
                  className="block w-full text-left"
                >
                  <span className="block font-serif text-[1rem] leading-snug text-ink">{turn.question}</span>
                  {turn.envelope?.conclusion ? (
                    <span className="mt-1 line-clamp-2 max-w-prose text-[0.8125rem] leading-relaxed text-ink-muted">
                      {turn.envelope.conclusion}
                    </span>
                  ) : turn.status ? (
                    <span className="mt-1 block text-[0.75rem] text-ink-faint">{STATUS_LABEL[turn.status]}</span>
                  ) : null}
                </button>
                {read.text || read.inherited.length > 0 ? (
                  <div className="mt-1.5">
                    <InterpretedAs text={read.text} inherited={read.inherited} />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="mt-2 text-[0.75rem] text-ink-faint">
          Follow-up questions here carry this question's metric and period forward.
        </p>
      )}
    </section>
  );
}
