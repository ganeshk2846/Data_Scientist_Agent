import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { AnswerCanvas } from '@/components/AnswerCanvas';
import { MockBar } from '@/components/MockBar';
import { AskBox } from '@/components/ask/AskBox';
import { AskHero } from '@/components/ask/AskHero';
import { PipelineTrack } from '@/components/pipeline/PipelineTrack';
import { AppShell } from '@/components/shell/AppShell';
import type { BackendState } from '@/components/shell/TopBar';
import { OfflineState } from '@/components/states/RunStates';
import { SectionLabel } from '@/components/ui/Card';
import { useAskHotkey } from '@/hooks/useHotkeys';
import { liveTransport, useRun } from '@/hooks/useRun';
import { useSession } from '@/hooks/useSession';
import { useTheme } from '@/hooks/useTheme';
import { probeBackend } from '@/lib/api';
import { mockTransport } from '@/lib/mock/transport';
import { isRunInFlight } from '@/lib/runState';

/** `?mock=1` previews every designed state without a backend. */
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

  const transport = useMemo(
    () => (mock ? mockTransport() : liveTransport(session.sessionId)),
    [mock, session.sessionId],
  );

  const run = useRun({
    transport,
    openHistory: session.open,
    onRunId: session.attachRunId,
    onEnvelope: session.settle,
  });

  const probe = useCallback(() => {
    if (mock) {
      setBackend('online');
      return;
    }
    void probeBackend().then((online) => setBackend(online ? 'online' : 'offline'));
  }, [mock]);

  // There is no health endpoint, so we probe a run id that cannot exist.
  useEffect(probe, [probe]);

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
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },
    [run],
  );

  const onSelectHistory = useCallback(
    (localId: string) => {
      setRailOpen(false);
      const entry = session.history.find((item) => item.localId === localId);
      if (entry?.envelope) run.restore(entry.envelope, entry.question, entry.localId);
    },
    [run, session.history],
  );

  const onNewQuestion = useCallback(() => {
    run.reset();
    setDraft('');
    setRailOpen(false);
    window.requestAnimationFrame(focusAsk);
  }, [focusAsk, run]);

  const onRetry = useCallback(() => {
    probe();
    const question = run.state.question;
    if (question) submit(question);
  }, [probe, run.state.question, submit]);

  const { state } = run;
  const idle = state.phase === 'idle';
  const inFlight = isRunInFlight(state.phase);
  // A restored answer has no live stages, and a finished one needs no track.
  const showTrack = state.stages.length > 0 && (inFlight || !!state.envelope);

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
        <div className="space-y-12">
          <AskHero
            value={draft}
            onChange={setDraft}
            onSubmit={() => submit(draft)}
            onPickSuggestion={(question) => submit(question)}
            inputRef={askRef}
          />

          {/* Offline is worth saying up front, not only after a failed ask. */}
          {!mock && backend === 'offline' ? (
            <div className="mx-auto max-w-3xl">
              <OfflineState
                detail="Nothing answered at /api, so questions cannot be submitted yet."
                onRetry={probe}
              />
            </div>
          ) : null}

          {mock ? (
            <div className="mx-auto max-w-3xl">
              <MockBar onPick={(question) => submit(question)} activeQuestion={null} />
            </div>
          ) : null}
        </div>
      ) : (
        <div className="space-y-10">
          <div>
            <SectionLabel>Question</SectionLabel>
            <h1 className="mt-3 max-w-prose font-serif text-h2 text-ink">
              {state.question}
            </h1>
          </div>

          {showTrack ? (
            <PipelineTrack
              stages={state.stages}
              phase={state.phase}
              reconnecting={state.reconnecting}
            />
          ) : null}

          <AnswerCanvas
            state={state}
            theme={theme.resolved}
            onAsk={(question) => submit(question)}
            onClarify={(answer, clarificationOf) => submit(answer, clarificationOf)}
            onRetry={onRetry}
          />

          {mock ? (
            <MockBar
              onPick={(question) => submit(question)}
              activeQuestion={state.question}
            />
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
