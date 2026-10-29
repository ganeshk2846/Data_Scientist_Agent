import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence } from 'framer-motion';

import { AnswerCanvas } from '@/components/AnswerCanvas';
import { MockBar } from '@/components/MockBar';
import { PresentationMode } from '@/components/PresentationMode';
import { AskBox } from '@/components/ask/AskBox';
import { AskHero } from '@/components/ask/AskHero';
import { CompareView } from '@/components/compare/CompareView';
import { ShortcutsSheet } from '@/components/help/ShortcutsSheet';
import { RunInspector } from '@/components/inspector/RunInspector';
import { CommandPalette } from '@/components/palette/CommandPalette';
import { Pinboard } from '@/components/pinboard/Pinboard';
import { PipelineSummaryBar, PipelineTrack } from '@/components/pipeline/PipelineTrack';
import { AppShell } from '@/components/shell/AppShell';
import type { View } from '@/components/shell/LeftRail';
import type { BackendState } from '@/components/shell/TopBar';
import { OfflineState } from '@/components/states/RunStates';
import { Tour } from '@/components/tour/Tour';
import { SectionLabel } from '@/components/ui/Card';
import { useToast } from '@/components/ui/Toast';
import { useDocumentStatus } from '@/hooks/useDocumentStatus';
import { useAskHotkey, useHotkey } from '@/hooks/useHotkeys';
import { usePins } from '@/hooks/usePins';
import { liveTransport, useRun } from '@/hooks/useRun';
import { useSession } from '@/hooks/useSession';
import { useSettings } from '@/hooks/useSettings';
import { useTheme } from '@/hooks/useTheme';
import { probeBackend } from '@/lib/api';
import { readHeadline } from '@/lib/headline';
import { mockTransport } from '@/lib/mock/transport';
import { isRunInFlight } from '@/lib/runState';
import { hasSeenTour, markTourSeen } from '@/lib/tour';

/** `?mock=1` previews every designed state without a backend. */
function readMockFlag(): boolean {
  return new URLSearchParams(window.location.search).get('mock') === '1';
}

/** `?tour=1` forces the first-run tour, for review and for the audit script. */
function readTourFlag(): boolean {
  return new URLSearchParams(window.location.search).get('tour') === '1';
}

const THEME_LABEL = { light: 'Light', dark: 'Dark', system: 'System' } as const;

export default function App() {
  const theme = useTheme();
  const settings = useSettings();
  const session = useSession();
  const toast = useToast();
  const [mock] = useState(readMockFlag);
  const [view, setView] = useState<View>('ask');
  const [railOpen, setRailOpen] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [draft, setDraft] = useState('');
  const [backend, setBackend] = useState<BackendState>('unknown');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [presenting, setPresenting] = useState(false);
  const [trackExpanded, setTrackExpanded] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
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

  const pins = usePins(transport);

  const probe = useCallback(() => {
    if (mock) {
      setBackend('online');
      return;
    }
    void probeBackend().then((online) => setBackend(online ? 'online' : 'offline'));
  }, [mock]);

  // There is no health endpoint, so we probe a run id that cannot exist.
  useEffect(probe, [probe]);

  const { state } = run;

  // The tab reports the run: title and a drawn favicon, both per status.
  useDocumentStatus(
    state.phase,
    state.envelope?.status ?? null,
    state.question,
    settings.accent,
  );

  const focusAsk = useCallback(() => {
    askRef.current?.focus();
    askRef.current?.select();
  }, []);

  /* ── The one submit path. Every surface funnels through here. ─────────── */
  const submit = useCallback(
    (question: string, clarificationOf: string | null = null) => {
      setView('ask');
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
      setView('ask');
      const entry = session.history.find((item) => item.localId === localId);
      if (entry?.envelope) {
        run.restore(entry.envelope, entry.question, entry.localId);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      } else {
        // A run we never collected an envelope for cannot be reopened from the
        // local cache, so the honest move is to offer to ask it again.
        toast.note('That run was not stored with an answer', 'Ask it again to see it');
      }
    },
    [run, session.history, toast],
  );

  const onNewQuestion = useCallback(() => {
    setView('ask');
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

  /* ── Star and pin, for the answer currently on the canvas ─────────────── */
  const activeEntry = session.history.find((entry) => entry.localId === state.localId);
  const starred = activeEntry?.starred ?? false;

  const toggleStar = useCallback(() => {
    if (!state.localId) return;
    session.toggleStar(state.localId);
    toast.done(starred ? 'Star removed' : 'Answer starred');
  }, [session, starred, state.localId, toast]);

  const headline = useMemo(
    () => (state.envelope ? readHeadline(state.envelope) : null),
    [state.envelope],
  );
  const pinned = state.question ? pins.isPinned(state.question) : false;

  const pinFigure = useCallback(() => {
    const envelope = state.envelope;
    const question = state.question;
    if (!envelope || !question) return;
    if (pins.isPinned(question)) {
      toast.note('That question is already on the pinboard');
      return;
    }
    const pin = pins.add(question, envelope);
    if (!pin) {
      toast.fault(
        'This answer states no single headline figure',
        'Only a one-cell result or an anomaly can be pinned',
      );
      return;
    }
    toast.done('Pinned to the pinboard', `${pin.unit}${pin.period ? ` · ${pin.period}` : ''}`);
  }, [pins, state.envelope, state.question, toast]);

  /* ── The keyboard ─────────────────────────────────────────────────────── */
  const canPresent = state.envelope?.status === 'answered';
  // While any overlay owns the screen, the single-letter bindings stand down.
  const bare = !paletteOpen && !shortcutsOpen && !inspectorOpen && !tourOpen && !presenting;

  useAskHotkey(() => setPaletteOpen(true));

  useHotkey('?', () => setShortcutsOpen((value) => !value), { enabled: bare || shortcutsOpen });
  useHotkey('p', () => canPresent && setPresenting((value) => !value), { enabled: bare });
  useHotkey('p', pinFigure, { shift: true, enabled: bare });
  useHotkey('s', toggleStar, { enabled: bare && !!state.localId });
  useHotkey('n', onNewQuestion, { enabled: bare });
  useHotkey('b', () => setView('pinboard'), { enabled: bare });
  useHotkey('i', () => setInspectorOpen(true), { enabled: bare && !!state.runId });

  // C copies the run's SQL — every query, in order, as one block.
  useHotkey(
    'c',
    () => {
      const queries = state.envelope?.queries ?? [];
      if (queries.length === 0) {
        toast.note('This run has no SQL to copy');
        return;
      }
      const sql = queries
        .map((query) => `-- ${query.query_id}\n${query.sql}`)
        .join('\n\n');
      void navigator.clipboard.writeText(sql).then(
        () =>
          toast.done(
            queries.length === 1 ? 'SQL copied' : `${queries.length} queries copied`,
          ),
        () => toast.fault('The clipboard refused the copy.'),
      );
    },
    { enabled: bare },
  );

  // J / K walk the rail, newest first, reopening as they go.
  const step = useCallback(
    (delta: number) => {
      const entries = session.history;
      if (entries.length === 0) return;
      const current = entries.findIndex((entry) => entry.localId === state.localId);
      const next = Math.min(
        entries.length - 1,
        Math.max(0, (current === -1 ? -1 : current) + delta),
      );
      const entry = entries[next];
      if (entry) onSelectHistory(entry.localId);
    },
    [onSelectHistory, session.history, state.localId],
  );
  useHotkey('j', () => step(1), { enabled: bare });
  useHotkey('k', () => step(-1), { enabled: bare });

  /* ── The first run ────────────────────────────────────────────────────── */
  useEffect(() => {
    if (hasSeenTour() && !readTourFlag()) return;
    // One frame, so the hero has laid out and the spotlight can measure it.
    const timer = window.setTimeout(() => setTourOpen(true), 900);
    return () => window.clearTimeout(timer);
  }, []);

  const closeTour = useCallback(() => {
    setTourOpen(false);
    markTourSeen();
  }, []);

  const clearHistory = useCallback(() => {
    session.clear();
    run.reset();
    toast.done('Stored history forgotten');
  }, [run, session, toast]);

  const idle = state.phase === 'idle';
  const inFlight = isRunInFlight(state.phase);
  const settledWithTrack = !inFlight && !!state.envelope && state.stages.length > 0;

  return (
    <>
      <AppShell
        theme={theme}
        settings={settings}
        backend={backend}
        runId={state.runId}
        mock={mock}
        history={session.history}
        activeId={state.localId}
        view={view}
        pinCount={pins.pins.length}
        railOpen={railOpen}
        railCollapsed={railCollapsed}
        wide={view === 'ask' && idle}
        onSelectHistory={onSelectHistory}
        onToggleStar={session.toggleStar}
        onNewQuestion={onNewQuestion}
        onSetView={(next) => {
          setView(next);
          setRailOpen(false);
        }}
        onToggleRail={() => setRailOpen((open) => !open)}
        onCloseRail={() => setRailOpen(false)}
        onToggleRailCollapsed={() => setRailCollapsed((value) => !value)}
        onOpenPalette={() => setPaletteOpen(true)}
        onOpenShortcuts={() => setShortcutsOpen(true)}
        onReplayTour={() => setTourOpen(true)}
        onClearHistory={clearHistory}
      >
        {view === 'pinboard' ? (
          <Pinboard
            pins={pins}
            onAsk={(question) => submit(question)}
            onEmptyAction={onNewQuestion}
          />
        ) : view === 'compare' ? (
          <CompareView history={session.history} onEmptyAction={onNewQuestion} />
        ) : idle ? (
          <div className="space-y-section">
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
          <div className="space-y-block">
            <div data-print="flow">
              <SectionLabel>Question</SectionLabel>
              <h1 className="opsz-title mt-4 max-w-prose font-serif text-[1.625rem] font-light leading-9 tracking-[-0.012em] text-ink">
                {state.question}
              </h1>
            </div>

            {/* Live: the full instrument. Settled: a slim bar, expandable. */}
            <div data-tour="pipeline">
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
                  onInspect={() => setInspectorOpen(true)}
                />
              ) : null}
            </div>

            <AnswerCanvas
              state={state}
              theme={theme.resolved}
              onAsk={(question) => submit(question)}
              onClarify={(answer, clarificationOf) => submit(answer, clarificationOf)}
              onRetry={onRetry}
              onPresent={() => setPresenting(true)}
              starred={starred}
              pinned={pinned}
              canPin={headline !== null}
              onToggleStar={toggleStar}
              onPin={pinFigure}
              onInspect={() => setInspectorOpen(true)}
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
              <div className="pointer-events-auto rounded-sm bg-[rgb(var(--c-bg)/0.72)] shadow-overlay backdrop-blur-xl">
                <AskBox
                  ref={askRef}
                  value={draft}
                  onChange={setDraft}
                  onSubmit={() => submit(draft)}
                  disabled={inFlight}
                  size="docked"
                  voice
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
        pinCount={pins.pins.length}
        onAsk={(question) => submit(question)}
        onOpenHistory={onSelectHistory}
        onNewQuestion={onNewQuestion}
        onToggleTheme={theme.cycle}
        onToggleMock={toggleMock}
        onPresentationMode={() => setPresenting(true)}
        onSetView={setView}
        onOpenShortcuts={() => setShortcutsOpen(true)}
        onReplayTour={() => setTourOpen(true)}
      />

      <ShortcutsSheet open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />

      <RunInspector
        open={inspectorOpen}
        onClose={() => setInspectorOpen(false)}
        stages={state.stages}
        envelope={state.envelope}
        runId={state.runId}
      />

      <Tour open={tourOpen} onClose={closeTour} />

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
