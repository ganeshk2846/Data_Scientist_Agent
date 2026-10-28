import { useCallback, useState } from 'react';

import { AppShell } from '@/components/shell/AppShell';
import { ShellPreview } from '@/components/ShellPreview';
import { useSession } from '@/hooks/useSession';
import { useTheme } from '@/hooks/useTheme';

/** `?mock=1` previews the design without a backend. Honoured from stage 4. */
function readMockFlag(): boolean {
  return new URLSearchParams(window.location.search).get('mock') === '1';
}

export default function App() {
  const theme = useTheme();
  const session = useSession();
  const [mock] = useState(readMockFlag);
  const [railOpen, setRailOpen] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);

  const onSelectHistory = useCallback((localId: string) => {
    setActiveId(localId);
    setRailOpen(false);
  }, []);

  const onNewQuestion = useCallback(() => {
    setActiveId(null);
    setRailOpen(false);
  }, []);

  return (
    <AppShell
      theme={theme}
      backend="unknown"
      runId={null}
      mock={mock}
      history={session.history}
      activeId={activeId}
      railOpen={railOpen}
      onSelectHistory={onSelectHistory}
      onNewQuestion={onNewQuestion}
      onToggleRail={() => setRailOpen((open) => !open)}
      onCloseRail={() => setRailOpen(false)}
    >
      <ShellPreview />
    </AppShell>
  );
}
