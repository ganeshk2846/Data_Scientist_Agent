import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence } from 'framer-motion';

import { AnswerCanvas } from '@/components/AnswerCanvas';
import { MockBar } from '@/components/MockBar';
import { PresentationMode } from '@/components/PresentationMode';
import { AskBox } from '@/components/ask/AskBox';
import { AskHero } from '@/components/ask/AskHero';
import { CommandPalette } from '@/components/palette/CommandPalette';
import { PipelineSummaryBar, PipelineTrack } from '@/components/pipeline/PipelineTrack';
import { AppShell } from '@/components/shell/AppShell';
import type { BackendState } from '@/components/shell/TopBar';
import { OfflineState } from '@/components/states/RunStates';
import { SectionLabel } from '@/components/ui/Card';
import { useAskHotkey, useHotkey } from '@/hooks/useHotkeys';
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

const THEME_LABEL = { light: 'Light', dark: 'Dark', system: 'System' } as const;

export default function App() {
  const theme = useTheme();
  const session = useSession();
  const [mock] = useState(readMockFlag);
  const [railOpen, setRailOpen] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [draft, setDraft] = useState('');
  const [backend, setBackend] = useState<BackendState>('unknown');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [presenting, setPresenting] = useState(false);
  const [trackExpanded, setTrackExpanded] = useState(false);
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

  // ⌘K opens the palette — the one surface for asking and for every action.
  useAskHotkey(() => setPaletteOpen(true));

  const { state } = run;
  const canPresent = state.envelope?.status === 'answered';

  // P toggles presentation mode, but never while typing.
  useHotkey('p', () => {
    if (canPresent) setPresenting((value) => !value);
  });

  const submit = useCallback(
    (question: string, clarificationOf: string | null = null) => {
      run.submit(question, clarificationOf);
      setDraft('');
      setRailOpen(false);
      setTrackExpanded(false);
      setPresenting(false);
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
    setPresenting(false);
    window.requestAnimationFrame(focusAsk);
  }, [focusAsk, run]);

  const onRetry = useCallback(() => {
    probe();
    const question = state.question;
    if (question) submit(question);
  }, [probe, state.question, submit]);

  const toggleMock = useCallback(() => {
    const url = new URL(window.location.href);
    if (mock) url.searchParams.delete('mock');
    else url.searchParams.set('mock', '1');
    window.location.href = url.toString();
  }, [mock]);

  const idle = state.phase === 'idle';
  const inFlight = isRunInFlight(state.phase);
  const settledWithTrack = !inFlight && !!state.envelope && state.stages.length > 0;

  return (
    <>
      <AppShell
        theme={theme}
        backend={backend}
        runId={state.runId}
        mock={mock}
        history={session.history}
        activeId={state.localId}
        railOpen={railOpen}
        railCollapsed={railCollapsed}
        wide={idle}
        onSelectHistory={onSelectHistory}
        onNewQuestion={onNewQuestion}
        onToggleRail={() => setRailOpen((open) => !open)}
        onCloseRail={() => setRailOpen(false)}
        onToggleRailCollapsed={() => setRailCollapsed((value) => !value)}
        onOpenPalette={() => setPaletteOpen(true)}
      >
        {idle ? (
          <div className="space-y-14">
            <AskHero
              value={draft}
              onChange={setDraft}
              onSubmit={() => submit(draft)}
              onPickSuggestion={(question) => submit(question)}
              inputRef={askRef}
            />

            {/* Offline is worth saying up front, not only after a failed ask. */}
            {!mock && backend === 'offline' ? (
              <div className="mx-auto max-w-2xl">
                <OfflineState
                  detail="Nothing answered at /api, so questions cannot be submitted yet."
                  onRetry={probe}
                />
              </div>
            ) : null}

            {mock ? (
              <div className="mx-auto max-w-2xl">
                <MockBar onPick={(question) => submit(question)} activeQuestion={null} />
              </div>
            ) : null}
          </div>
        ) : (
          <div className="space-y-10">
            <div data-print="flow">
              <SectionLabel>Question</SectionLabel>
              <h1 className="mt-3 max-w-prose font-serif text-[1.625rem] leading-snug text-ink">
                {state.question}
              </h1>
            </div>

            {/* Live: the full instrument. Settled: a slim bar, expandable. */}
            {inFlight || trackExpanded ? (
              <PipelineTrack
                stages={state.stages}
                phase={state.phase}
                reconnecting={state.reconnecting}
                startedAt={state.startedAt}
              />
            ) : null}
            {settledWithTrack ? (
              <PipelineSummaryBar
                stages={state.stages}
                expanded={trackExpanded}
                onExpand={() => setTrackExpanded((value) => !value)}
              />
            ) : null}

            <AnswerCanvas
              state={state}
              theme={theme.resolved}
              onAsk={(question) => submit(question)}
              onClarify={(answer, clarificationOf) => submit(answer, clarificationOf)}
              onRetry={onRetry}
              onPresent={() => setPresenting(true)}
            />

            {mock ? (
              <MockBar
                onPick={(question) => submit(question)}
                activeQuestion={state.question}
              />
            ) : null}

            {/* A floating composer. It must read as a layer above the page —
                otherwise it looks like a hole punched in whatever it covers. */}
            <div
              className="pointer-events-none sticky bottom-5 z-20 pt-6"
              data-print="hide"
            >
              <div className="pointer-events-auto rounded-[3px] bg-[rgb(var(--c-bg)/0.72)] shadow-overlay backdrop-blur-xl">
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
          </div>
        )}
      </AppShell>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        history={session.history}
        mock={mock}
        themeLabel={THEME_LABEL[theme.setting]}
        canPresent={canPresent}
        onAsk={(question) => submit(question)}
        onOpenHistory={onSelectHistory}
        onNewQuestion={onNewQuestion}
        onToggleTheme={theme.cycle}
        onToggleMock={toggleMock}
        onPresentationMode={() => setPresenting(true)}
      />

      <AnimatePresence>
        {presenting && state.envelope ? (
          <PresentationMode
            envelope={state.envelope}
            question={state.question}
            theme={theme.resolved}
            onClose={() => setPresenting(false)}
          />
        ) : null}
      </AnimatePresence>
    </>
  );
}
