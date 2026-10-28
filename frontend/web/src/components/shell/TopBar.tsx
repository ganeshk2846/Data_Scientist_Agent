import { PanelLeft } from 'lucide-react';

import { ThemeToggle } from './ThemeToggle';
import { Kbd } from '@/components/ui/Button';
import { cx } from '@/lib/cx';
import { shortRunId } from '@/lib/format';
import type { ThemeController } from '@/hooks/useTheme';

/** Whether the backend answered our probe. */
export type BackendState = 'unknown' | 'online' | 'offline';

interface TopBarProps {
  theme: ThemeController;
  backend: BackendState;
  runId: string | null;
  mock: boolean;
  onToggleRail: () => void;
  onOpenPalette: () => void;
}

const DOT: Record<BackendState, string> = {
  unknown: 'bg-ink-faint',
  online: 'bg-sage',
  offline: 'bg-terracotta',
};

const DOT_LABEL: Record<BackendState, string> = {
  unknown: 'Connecting',
  online: 'Live',
  offline: 'Offline',
};

export function TopBar({
  theme,
  backend,
  runId,
  mock,
  onToggleRail,
  onOpenPalette,
}: TopBarProps) {
  return (
    <header
      data-print="hide"
      className={cx(
        'sticky top-0 z-30 flex h-14 items-center gap-4 px-4 sm:px-6',
        // Glass is allowed here: the bar is an overlay, not a content surface.
        'border-b border-hairline bg-[rgb(var(--c-bg)/0.78)] backdrop-blur-xl',
      )}
    >
      <button
        type="button"
        onClick={onToggleRail}
        aria-label="Toggle question history"
        className="-ml-1.5 rounded-[3px] p-1.5 text-ink-faint transition-colors duration-micro hover:text-ink lg:hidden"
      >
        <PanelLeft size={16} strokeWidth={1.75} aria-hidden />
      </button>

      {/* Wordmark: a gold index mark, then the name. */}
      <div className="flex min-w-0 items-center gap-2.5">
        <span aria-hidden className="h-3 w-px bg-gold" />
        <span className="font-serif text-[0.9375rem] tracking-[-0.01em] text-ink">
          Data Scientist
        </span>
      </div>

      <div className="ml-auto flex items-center gap-2 sm:gap-4">
        {mock ? (
          <span className="rounded-[3px] border border-gold bg-[var(--c-gold-wash)] px-2 py-0.5 text-micro uppercase tracking-label text-gold-ink">
            Mock
          </span>
        ) : null}

        {runId ? (
          <span className="hidden font-mono text-[0.6875rem] tracking-tight text-ink-faint lg:block">
            {shortRunId(runId)}
          </span>
        ) : null}

        {/* The ⌘K affordance, as a real button. */}
        <button
          type="button"
          onClick={onOpenPalette}
          // No aria-label: the accessible name comes from the visible word,
          // with the key caps hidden from the a11y tree. A label here could
          // only ever disagree with what the button actually says.
          title="Search questions, history and actions"
          className={cx(
            'hidden items-center gap-2 rounded-[3px] border border-hairline bg-surface/60 py-1 pl-2.5 pr-1.5 sm:flex',
            'text-[0.6875rem] text-ink-faint transition-colors duration-micro ease-editorial',
            'hover:border-gold hover:text-ink',
          )}
        >
          <span>Search</span>
          <span aria-hidden className="flex items-center gap-1">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
          </span>
        </button>

        <span
          className="flex items-center gap-2 pl-1"
          title={
            backend === 'online'
              ? 'The agent service is responding'
              : backend === 'offline'
                ? 'Nothing is answering at /api'
                : 'Checking the agent service'
          }
        >
          <span className="relative flex h-1.5 w-1.5">
            {backend === 'online' ? (
              <span
                aria-hidden
                className="absolute inset-0 rounded-full bg-sage motion-safe:animate-[pulse-soft_2.8s_ease-in-out_infinite]"
              />
            ) : (
              <span aria-hidden className={cx('absolute inset-0 rounded-full', DOT[backend])} />
            )}
          </span>
          <span className="sr-only">{DOT_LABEL[backend]}</span>
          <span className="hidden text-micro uppercase tracking-label text-ink-faint md:block">
            {DOT_LABEL[backend]}
          </span>
        </span>

        <ThemeToggle theme={theme} />
      </div>
    </header>
  );
}
