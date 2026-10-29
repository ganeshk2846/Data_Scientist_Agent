import type { ReactNode } from 'react';

import { LeftRail, type View } from './LeftRail';
import { TopBar, type BackendState } from './TopBar';
import { cx } from '@/lib/cx';
import type { HistoryEntry } from '@/hooks/useSession';
import type { SettingsController } from '@/hooks/useSettings';
import type { ThemeController } from '@/hooks/useTheme';

interface AppShellProps {
  children: ReactNode;
  theme: ThemeController;
  settings: SettingsController;
  backend: BackendState;
  runId: string | null;
  mock: boolean;
  history: readonly HistoryEntry[];
  activeId: string | null;
  view: View;
  pinCount: number;
  railOpen: boolean;
  railCollapsed: boolean;
  /** The hero stage spans the full canvas; a briefing reads narrower. */
  wide?: boolean;
  onSelectHistory: (localId: string) => void;
  onToggleStar: (localId: string) => void;
  onNewQuestion: () => void;
  onSetView: (view: View) => void;
  onToggleRail: () => void;
  onCloseRail: () => void;
  onToggleRailCollapsed: () => void;
  onOpenPalette: () => void;
  onOpenShortcuts: () => void;
  onReplayTour: () => void;
  onClearHistory: () => void;
}

/**
 * The page frame: sticky top bar, sticky left rail on wide screens, centred
 * canvas on a 12-column grid. The grain sits on the outermost element so it
 * tints everything once, below all content.
 */
export function AppShell({
  children,
  theme,
  settings,
  backend,
  runId,
  mock,
  history,
  activeId,
  view,
  pinCount,
  railOpen,
  railCollapsed,
  wide = false,
  onSelectHistory,
  onToggleStar,
  onNewQuestion,
  onSetView,
  onToggleRail,
  onCloseRail,
  onToggleRailCollapsed,
  onOpenPalette,
  onOpenShortcuts,
  onReplayTour,
  onClearHistory,
}: AppShellProps) {
  return (
    <div className="paper-grain min-h-screen">
      <div className="relative z-10">
        <TopBar
          theme={theme}
          settings={settings}
          backend={backend}
          runId={runId}
          mock={mock}
          historyCount={history.length}
          onToggleRail={onToggleRail}
          onOpenPalette={onOpenPalette}
          onOpenShortcuts={onOpenShortcuts}
          onReplayTour={onReplayTour}
          onClearHistory={onClearHistory}
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
            view={view}
            pinCount={pinCount}
            open={railOpen}
            collapsed={railCollapsed}
            onSelect={onSelectHistory}
            onToggleStar={onToggleStar}
            onNewQuestion={onNewQuestion}
            onSetView={onSetView}
            onClose={onCloseRail}
            onToggleCollapsed={onToggleRailCollapsed}
          />

          <main
            className={cx(
              'min-w-0 px-5 pb-32 sm:px-8',
              wide ? 'pt-4 sm:pt-8' : 'pt-8 sm:pt-12 lg:px-12',
            )}
          >
            {/* The 12-column grid every view composes on. The canvas takes all
                twelve; a view that wants a narrower measure takes fewer. */}
            <div
              className={cx(
                'mx-auto grid w-full grid-cols-12 gap-x-6',
                wide ? 'max-w-5xl' : 'max-w-canvas',
              )}
            >
              <div className="col-span-12 min-w-0">{children}</div>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
