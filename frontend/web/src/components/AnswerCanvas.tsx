import { Briefing } from '@/components/briefing/Briefing';
import { BriefingSkeleton } from '@/components/briefing/BriefingSkeleton';
import { QueryList } from '@/components/queries/QueryList';
import {
  BlockedState,
  ClarifyState,
  ErrorState,
  InsufficientEvidenceState,
  OfflineState,
  RefusedState,
} from '@/components/states/RunStates';
import { CaveatCallout, RunMetricsFooter } from '@/components/briefing/BriefingParts';
import type { ClarifyChoice } from '@/components/ask/ClarifyOptions';
import type { ResolvedTheme } from '@/lib/theme';
import { asV2 } from '@/lib/v2';
import type { ReactNode } from 'react';
import type { RunState } from '@/lib/runState';
import { isRunInFlight } from '@/lib/runState';

interface AnswerCanvasProps {
  state: RunState;
  theme: ResolvedTheme;
  onAsk: (question: string) => void;
  onClarify: (answer: string, clarificationOf: string) => void;
  /** V2: answer a clarification with one of its options. */
  onChooseOption?: (optionId: string, label: string, clarificationOf: string) => void;
  /** Rendered under an answered briefing's trust panel (the feedback control). */
  afterTrust?: ReactNode;
  onRetry: () => void;
  onPresent: () => void;
  /** The briefing's own actions, threaded through from App. */
  starred: boolean;
  pinned: boolean;
  canPin: boolean;
  onToggleStar: () => void;
  onPin: () => void;
  onInspect: () => void;
}

/**
 * Chooses what the main canvas shows for a run: the full briefing for an
 * answered envelope, a designed state for every other status, and the skeleton
 * while the run is still in flight.
 */
export function AnswerCanvas({
  state,
  theme,
  onAsk,
  onClarify,
  onChooseOption,
  afterTrust,
  onRetry,
  onPresent,
  starred,
  pinned,
  canPin,
  onToggleStar,
  onPin,
  onInspect,
}: AnswerCanvasProps) {
  // A client-side failure never reached a status, so it is handled first.
  if (state.failure) {
    return state.failure.kind === 'offline' ? (
      <OfflineState detail={state.failure.detail} onRetry={onRetry} />
    ) : (
      <ErrorState
        detail={state.failure.detail}
        streamError={state.streamError}
        onRetry={onRetry}
      />
    );
  }

  if (isRunInFlight(state.phase)) {
    // The clarify event arrives before the terminal one, so it can be shown
    // while the envelope is still being collected.
    if (state.clarify && state.runId) {
      const live = state.clarify;
      const choice: ClarifyChoice | null =
        live.options && live.options.length > 0
          ? {
              question: live.question ?? live.what_needs_clarification,
              options: live.options,
              defaultOptionId: live.default_option_id ?? null,
              defaultRationale: null,
              round: live.round ?? 1,
            }
          : null;
      return (
        <ClarifyState
          choice={choice}
          {...(onChooseOption ? { onChoose: onChooseOption } : {})}
          clarification={{
            what_understood: state.clarify.what_understood,
            what_needs_clarification: state.clarify.what_needs_clarification,
          }}
          runId={state.runId}
          onClarify={onClarify}
        />
      );
    }
    return <BriefingSkeleton />;
  }

  const envelope = state.envelope;
  if (!envelope) return null;

  switch (envelope.status) {
    case 'answered':
      return (
        <Briefing
          envelope={envelope}
          theme={theme}
          question={state.question}
          onAsk={onAsk}
          onPresent={onPresent}
          starred={starred}
          pinned={pinned}
          canPin={canPin}
          onToggleStar={onToggleStar}
          onPin={onPin}
          onInspect={onInspect}
          afterTrust={afterTrust}
        />
      );

    case 'clarify': {
      const request = asV2(envelope)?.clarification ?? null;
      const choice: ClarifyChoice | null = request
        ? {
            question: request.question,
            options: request.options,
            defaultOptionId: request.default_assumption.option_id,
            defaultRationale: request.default_assumption.rationale,
            round: request.round,
          }
        : null;
      return (
        <div className="space-y-block">
          {envelope.clarification ? (
            <ClarifyState
              choice={choice}
              {...(onChooseOption ? { onChoose: onChooseOption } : {})}
              clarification={envelope.clarification}
              runId={envelope.run_id}
              onClarify={onClarify}
            />
          ) : null}
          <Tail envelope={envelope} />
        </div>
      );
    }

    case 'refused':
      return (
        <div className="space-y-block">
          {envelope.refusal ? (
            <RefusedState refusal={envelope.refusal} onAsk={onAsk} />
          ) : null}
          <Tail envelope={envelope} />
        </div>
      );

    case 'blocked':
      return (
        <div className="space-y-block">
          {envelope.block ? <BlockedState block={envelope.block} /> : null}
          <Tail envelope={envelope} />
        </div>
      );

    case 'insufficient_evidence':
      return (
        <div className="space-y-block">
          <InsufficientEvidenceState envelope={envelope} />
          {envelope.queries.length > 0 ? (
            <QueryList
              queries={envelope.queries}
              claims={envelope.claims}
              origin={envelope.queries[0]?.origin ?? null}
            />
          ) : null}
          <Tail envelope={envelope} skipCaveats />
        </div>
      );

    case 'error':
      return (
        <div className="space-y-block">
          <ErrorState
            detail={envelope.caveats[0] ?? envelope.route.reason}
            streamError={state.streamError}
            onRetry={onRetry}
          />
          <Tail envelope={envelope} skipCaveats />
        </div>
      );
  }
}

/** Shared footer matter: caveats, then the metrics strip. */
function Tail({
  envelope,
  skipCaveats = false,
}: {
  envelope: NonNullable<RunState['envelope']>;
  skipCaveats?: boolean;
}) {
  return (
    <>
      {!skipCaveats ? (
        <CaveatCallout
          caveats={envelope.caveats}
          causalBoundaryNote={envelope.causal_boundary_note}
        />
      ) : null}
      <RunMetricsFooter
        metrics={envelope.run_metrics}
        method={envelope.method}
        provenance={envelope.provenance}
        contractVersion={envelope.contract_version}
      />
    </>
  );
}
