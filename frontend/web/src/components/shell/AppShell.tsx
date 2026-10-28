import type { ReactNode } from 'react';

import { LeftRail } from './LeftRail';
import { TopBar, type BackendState } from './TopBar';
import { cx } from '@/lib/cx';
import type { HistoryEntry } from '@/hooks/useSession';
import type { ThemeController } from '@/hooks/useTheme';

interface AppShellProps {
  children: ReactNode;
  theme: ThemeController;
  backend: BackendState;
  runId: string | null;
  mock: boolean;
  history: readonly HistoryEntry[];
  activeId: string | null;
  railOpen: boolean;
  railCollapsed: boolean;
  /** The hero stage spans the full canvas; a briefing reads narrower. */
  wide?: boolean;
  onSelectHistory: (localId: string) => void;
  onNewQuestion: () => void;
  onToggleRail: () => void;
  onCloseRail: () => void;
  onToggleRailCollapsed: () => void;
  onOpenPalette: () => void;
}

/**
 * The page frame: sticky top bar, sticky left rail on wide screens, centred
 * canvas. The grain sits on the outermost element so it tints everything once,
 * below all content.
 */
export function AppShell({
  children,
  theme,
  backend,
  runId,
  mock,
  history,
  activeId,
  railOpen,
  railCollapsed,
  wide = false,
  onSelectHistory,
  onNewQuestion,
  onToggleRail,
  onCloseRail,
  onToggleRailCollapsed,
  onOpenPalette,
}: AppShellProps) {
  return (
    <div className="paper-grain min-h-screen">
      <div className="relative z-10">
        <TopBar
          theme={theme}
          backend={backend}
          runId={runId}
          mock={mock}
          onToggleRail={onToggleRail}
          onOpenPalette={onOpenPalette}
        />

        <div
          className={cx(
            'lg:grid',
            railCollapsed
              ? 'lg:grid-cols-[4rem_minmax(0,1fr)]'
              : 'lg:grid-cols-[17rem_minmax(0,1fr)]',
          )}
        >
          <LeftRail
            history={history}
            activeId={activeId}
            open={railOpen}
            collapsed={railCollapsed}
            onSelect={onSelectHistory}
            onNewQuestion={onNewQuestion}
            onClose={onCloseRail}
            onToggleCollapsed={onToggleRailCollapsed}
          />

          <main
            className={cx(
              'min-w-0 px-5 pb-32 sm:px-8',
              wide ? 'pt-4 sm:pt-8' : 'pt-8 sm:pt-12 lg:px-12',
            )}
          >
            <div className={cx('mx-auto w-full', wide ? 'max-w-5xl' : 'max-w-canvas')}>
              {children}
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
