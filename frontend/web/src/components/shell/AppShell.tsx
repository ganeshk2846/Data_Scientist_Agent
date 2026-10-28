import type { ReactNode } from 'react';

import { LeftRail } from './LeftRail';
import { TopBar, type BackendState } from './TopBar';
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
  onSelectHistory: (localId: string) => void;
  onNewQuestion: () => void;
  onToggleRail: () => void;
  onCloseRail: () => void;
}

/**
 * The page frame: sticky top bar, sticky left rail on wide screens, and a
 * centred main canvas. The grain sits on the outermost element so it tints
 * everything once, below all content.
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
  onSelectHistory,
  onNewQuestion,
  onToggleRail,
  onCloseRail,
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
        />

        <div className="lg:grid lg:grid-cols-[var(--rail-w)_minmax(0,1fr)] [--rail-w:17rem]">
          <LeftRail
            history={history}
            activeId={activeId}
            open={railOpen}
            onSelect={onSelectHistory}
            onNewQuestion={onNewQuestion}
            onClose={onCloseRail}
          />

          <main className="min-w-0 px-5 pb-28 pt-8 sm:px-8 sm:pt-12 lg:px-14">
            <div className="mx-auto w-full max-w-canvas">{children}</div>
          </main>
        </div>
      </div>
    </div>
  );
}
