import { PlayCircle } from 'lucide-react';

import { SectionLabel } from '@/components/ui/Card';
import type { HistoryEntry } from '@/hooks/useSession';
import { formatRelativeTime } from '@/lib/format';

export interface Conversation {
  threadId: string;
  /** Oldest first. */
  turns: readonly HistoryEntry[];
}

/** Groups stored questions into conversations, newest conversation first. */
export function groupConversations(history: readonly HistoryEntry[]): readonly Conversation[] {
  const byThread = new Map<string, HistoryEntry[]>();
  for (const entry of history) {
    const key = entry.threadId ?? entry.localId;
    const list = byThread.get(key) ?? [];
    list.push(entry);
    byThread.set(key, list);
  }
  return [...byThread.entries()].map(([threadId, entries]) => ({
    threadId,
    turns: [...entries].reverse(),
  }));
}

/**
 * Past conversations stored in this browser, each replayable turn by turn
 * (Track 5, item 8). Only turns with a stored answer can be replayed.
 */
export function ConversationList({
  conversations,
  onReplay,
}: {
  conversations: readonly Conversation[];
  onReplay: (threadId: string) => void;
}) {
  const replayable = conversations.filter((item) => item.turns.some((turn) => turn.envelope)).slice(0, 5);
  if (replayable.length === 0) return null;
  return (
    <section className="mx-auto max-w-2xl" data-testid="conversation-list">
      <SectionLabel>Replay a past conversation · stored in this browser</SectionLabel>
      <ul className="mt-3 divide-y divide-hairline rounded-sm border border-hairline bg-surface">
        {replayable.map((conversation) => {
          const first = conversation.turns[0];
          if (!first) return null;
          return (
            <li key={conversation.threadId}>
              <button
                type="button"
                onClick={() => onReplay(conversation.threadId)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-hover hover:bg-sunken"
              >
                <PlayCircle size={14} strokeWidth={1.5} aria-hidden className="shrink-0 text-ink-faint" />
                <span className="min-w-0 flex-1 truncate text-small text-ink">{first.question}</span>
                <span className="shrink-0 text-[0.6875rem] text-ink-faint">
                  {conversation.turns.length} {conversation.turns.length === 1 ? 'turn' : 'turns'} ·{' '}
                  {formatRelativeTime(first.askedAt)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
