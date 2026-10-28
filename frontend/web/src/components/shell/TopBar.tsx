import { PanelLeft } from 'lucide-react';

import { ThemeToggle } from './ThemeToggle';
import { cx } from '@/lib/cx';
import { shortRunId } from '@/lib/format';
import type { ThemeController } from '@/hooks/useTheme';

/** Whether the backend answered our probe. Wired up in stage 2. */
export type BackendState = 'unknown' | 'online' | 'offline';

interface TopBarProps {
  theme: ThemeController;
  backend: BackendState;
  runId: string | null;
  mock: boolean;
  onToggleRail: () => void;
}

const DOT: Record<BackendState, string> = {
  unknown: 'bg-ink-faint',
  online: 'bg-sage',
  offline: 'bg-terracotta',
};

const DOT_LABEL: Record<BackendState, string> = {
  unknown: 'Connecting',
  online: 'Connected',
  offline: 'Backend offline',
};

export function TopBar({ theme, backend, runId, mock, onToggleRail }: TopBarProps) {
  return (
    <header
      className={cx(
        'sticky top-0 z-30 flex h-16 items-center gap-4 px-5 sm:px-8',
        'border-b border-hairline bg-[rgb(var(--c-bg)/0.82)] backdrop-blur-md',
      )}
    >
      <button
        type="button"
        onClick={onToggleRail}
        aria-label="Toggle question history"
        className="-ml-1.5 rounded-sm p-1.5 text-ink-faint transition-colors duration-micro hover:text-ink lg:hidden"
      >
        <PanelLeft size={17} strokeWidth={1.75} aria-hidden />
      </button>

      <div className="flex min-w-0 items-baseline gap-3">
        <span className="font-serif text-[1.0625rem] tracking-tight text-ink">
          Data Scientist
        </span>
        <span aria-hidden className="hidden h-3 w-px bg-hairline-strong sm:block" />
        <span className="hidden text-micro uppercase text-ink-faint sm:block">
          Decision intelligence
        </span>
      </div>

      <div className="ml-auto flex items-center gap-3 sm:gap-5">
        {mock ? (
          <span className="rounded-sm border border-gold px-2 py-0.5 text-micro uppercase text-gold">
            Mock
          </span>
        ) : null}

        {runId ? (
          <span className="hidden font-mono text-[0.6875rem] text-ink-faint sm:block">
            {shortRunId(runId)}
          </span>
        ) : null}

        <span className="flex items-center gap-2" title={DOT_LABEL[backend]}>
          <span aria-hidden className={cx('h-1.5 w-1.5 rounded-full', DOT[backend])} />
          <span className="sr-only">{DOT_LABEL[backend]}</span>
          <span className="hidden text-micro uppercase text-ink-faint md:block">
            {DOT_LABEL[backend]}
          </span>
        </span>

        <ThemeToggle theme={theme} />
      </div>
    </header>
  );
}
