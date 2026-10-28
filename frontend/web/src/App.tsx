import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { AskBox } from '@/components/ask/AskBox';
import { AskHero } from '@/components/ask/AskHero';
import { Briefing } from '@/components/briefing/Briefing';
import { BriefingSkeleton } from '@/components/briefing/BriefingSkeleton';
import { PipelineTrack } from '@/components/pipeline/PipelineTrack';
import { AppShell } from '@/components/shell/AppShell';
import type { BackendState } from '@/components/shell/TopBar';
import { Card, SectionLabel } from '@/components/ui/Card';
import { useAskHotkey } from '@/hooks/useHotkeys';
import { useRun, liveTransport } from '@/hooks/useRun';
import { useSession } from '@/hooks/useSession';
import { useTheme } from '@/hooks/useTheme';
import { probeBackend } from '@/lib/api';
import { isRunInFlight } from '@/lib/runState';

/** `?mock=1` previews the design without a backend. */
function readMockFlag(): boolean {
  return new URLSearchParams(window.location.search).get('mock') === '1';
}

export default function App() {
  const theme = useTheme();
  const session = useSession();
  const [mock] = useState(readMockFlag);
  const [railOpen, setRailOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [backend, setBackend] = useState<BackendState>('unknown');
  const askRef = useRef<HTMLTextAreaElement>(null);

  const transport = useMemo(() => liveTransport(session.sessionId), [session.sessionId]);

  const run = useRun({
    transport,
    openHistory: session.open,
    onRunId: session.attachRunId,
    onEnvelope: session.settle,
  });

  // The status dot: no health endpoint exists, so we probe a run that cannot be.
  useEffect(() => {
    if (mock) {
      setBackend('online');
      return;
    }
    let live = true;
    void probeBackend().then((online) => {
      if (live) setBackend(online ? 'online' : 'offline');
    });
    return () => {
      live = false;
    };
  }, [mock, run.state.failure]);

  const focusAsk = useCallback(() => {
    askRef.current?.focus();
    askRef.current?.select();
  }, []);
  useAskHotkey(focusAsk);

  const submit = useCallback(
    (question: string, clarificationOf: string | null = null) => {
      run.submit(question, clarificationOf);
      setDraft('');
      setRailOpen(false);
    },
    [run],
  );

  const onSelectHistory = useCallback(
    (localId: string) => {
      const entry = session.history.find((item) => item.localId === localId);
      setRailOpen(false);
      if (!entry) return;
      if (entry.envelope) run.restore(entry.envelope, entry.question, entry.localId);
    },
    [run, session.history],
  );

  const onNewQuestion = useCallback(() => {
    run.reset();
    setDraft('');
    setRailOpen(false);
    // Let the hero mount before handing it focus.
    window.requestAnimationFrame(focusAsk);
  }, [focusAsk, run]);

  const { state } = run;
  const idle = state.phase === 'idle';
  const inFlight = isRunInFlight(state.phase);

  return (
    <AppShell
      theme={theme}
      backend={backend}
      runId={state.runId}
      mock={mock}
      history={session.history}
      activeId={state.localId}
      railOpen={railOpen}
      onSelectHistory={onSelectHistory}
      onNewQuestion={onNewQuestion}
      onToggleRail={() => setRailOpen((open) => !open)}
      onCloseRail={() => setRailOpen(false)}
    >
      {idle ? (
        <AskHero
          value={draft}
          onChange={setDraft}
          onSubmit={() => submit(draft)}
          onPickSuggestion={(question) => submit(question)}
          inputRef={askRef}
        />
      ) : (
        <div className="space-y-10">
          <div>
            <SectionLabel>Question</SectionLabel>
            <h1 className="mt-3 max-w-prose font-serif text-h2 text-ink">
              {state.question}
            </h1>
          </div>

          <PipelineTrack
            stages={state.stages}
            phase={state.phase}
            reconnecting={state.reconnecting}
          />

          {inFlight ? <BriefingSkeleton /> : null}

          {state.envelope ? (
            <Briefing envelope={state.envelope} theme={theme.resolved} />
          ) : null}

          {state.failure ? (
            <Card className="p-6 sm:p-8">
              <h2 className="text-h3 font-sans text-ink">{state.failure.title}</h2>
              <p className="mt-2 max-w-prose text-body text-ink-muted">
                {state.failure.detail}
              </p>
            </Card>
          ) : null}

          <div className="sticky bottom-6 pt-2">
            <AskBox
              ref={askRef}
              value={draft}
              onChange={setDraft}
              onSubmit={() => submit(draft)}
              disabled={inFlight}
              size="docked"
              placeholder={inFlight ? 'Working…' : 'Ask a follow-up…'}
            />
          </div>
        </div>
      )}
    </AppShell>
  );
}
