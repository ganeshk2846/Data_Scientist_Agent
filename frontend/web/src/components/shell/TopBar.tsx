import { Keyboard, PanelLeft } from 'lucide-react';

import { ThemeToggle } from './ThemeToggle';
import { SettingsPopover } from '@/components/settings/SettingsPopover';
import { Kbd } from '@/components/ui/Button';
import { cx } from '@/lib/cx';
import { shortRunId } from '@/lib/format';
import type { SettingsController } from '@/hooks/useSettings';
import type { ThemeController } from '@/hooks/useTheme';

/** Whether the backend answered our probe. */
export type BackendState = 'unknown' | 'online' | 'offline';

interface TopBarProps {
  theme: ThemeController;
  settings: SettingsController;
  backend: BackendState;
  runId: string | null;
  mock: boolean;
  historyCount: number;
  onToggleRail: () => void;
  onOpenPalette: () => void;
  onOpenShortcuts: () => void;
  onReplayTour: () => void;
  onClearHistory: () => void;
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
  settings,
  backend,
  runId,
  mock,
  historyCount,
  onToggleRail,
  onOpenPalette,
  onOpenShortcuts,
  onReplayTour,
  onClearHistory,
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
        title="Navigation and stored questions"
        className="-ml-1.5 rounded-sm p-1.5 text-ink-faint transition-colors duration-hover hover:text-ink lg:hidden"
      >
        <PanelLeft size={16} strokeWidth={1.5} aria-hidden />
        <span className="sr-only">Toggle the rail</span>
      </button>

      {/* Wordmark: an accent index mark, then the name. */}
      <div className="flex min-w-0 items-center gap-2.5">
        <span aria-hidden className="h-3 w-px bg-accent" />
        <span className="opsz-text font-serif text-[0.9375rem] tracking-[-0.01em] text-ink">
          Data Scientist
        </span>
      </div>

      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        {mock ? (
          <span className="rounded-sm border border-hairline-strong px-2 py-0.5 text-micro uppercase tracking-label text-ink-muted">
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
            'hidden items-center gap-2 rounded-sm border border-hairline bg-surface/60 py-1 pl-2.5 pr-1.5 sm:flex',
            'text-[0.6875rem] text-ink-faint transition-colors duration-hover ease-editorial',
            'hover:border-hairline-strong hover:text-ink',
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

        <span aria-hidden className="hidden h-4 w-px bg-hairline sm:block" />

        <button
          type="button"
          onClick={onOpenShortcuts}
          title="Keyboard shortcuts (?)"
          className="hidden rounded-sm p-1.5 text-ink-faint transition-colors duration-hover hover:text-ink sm:block"
        >
          <Keyboard size={16} strokeWidth={1.5} aria-hidden />
          <span className="sr-only">Keyboard shortcuts</span>
        </button>

        <ThemeToggle theme={theme} />

        <SettingsPopover
          settings={settings}
          historyCount={historyCount}
          onReplayTour={onReplayTour}
          onClearHistory={onClearHistory}
        />
      </div>
    </header>
  );
}
