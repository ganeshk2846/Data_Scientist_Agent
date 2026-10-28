import {
  CircleSlash,
  CloudOff,
  HelpCircle,
  ScanSearch,
  ShieldX,
  TriangleAlert,
} from 'lucide-react';
import { useState } from 'react';

import { StateField, StateShell } from './StateShell';
import { AskBox } from '@/components/ask/AskBox';
import { Tag } from '@/components/briefing/StatusBadge';
import { Button } from '@/components/ui/Button';
import { Card, SectionLabel } from '@/components/ui/Card';
import { humanise } from '@/lib/format';
import type {
  AnswerEnvelope,
  BlockBlock,
  ClarificationResult,
  RefusalBlock,
} from '@/types/envelope';
import type { ErrorEvent } from '@/types/events';

/* ---------- clarify ---------- */

interface ClarifyStateProps {
  clarification: ClarificationResult;
  /** The run being clarified; sent back as `clarification_of`. */
  runId: string;
  onClarify: (answer: string, clarificationOf: string) => void;
}

export function ClarifyState({ clarification, runId, onClarify }: ClarifyStateProps) {
  const [reply, setReply] = useState('');

  return (
    <StateShell
      Icon={HelpCircle}
      tone="gold"
      eyebrow="Needs clarifying"
      title="One detail short of an answer"
      lede={clarification.what_needs_clarification}
    >
      <div className="space-y-7">
        <StateField label="What was understood">
          {clarification.what_understood}
        </StateField>

        <div>
          <SectionLabel>Your reply</SectionLabel>
          <div className="mt-2.5">
            <AskBox
              value={reply}
              onChange={setReply}
              onSubmit={() => {
                if (reply.trim()) onClarify(reply, runId);
              }}
              size="docked"
              placeholder="Add the missing metric or period…"
            />
          </div>
          <p className="mt-2.5 font-mono text-[0.6875rem] text-ink-faint">
            sent as clarification_of {runId.slice(0, 12)}
          </p>
        </div>
      </div>
    </StateShell>
  );
}

/* ---------- refused ---------- */

interface RefusedStateProps {
  refusal: RefusalBlock;
  onAsk: (question: string) => void;
}

export function RefusedState({ refusal, onAsk }: RefusedStateProps) {
  return (
    <StateShell
      Icon={CircleSlash}
      eyebrow="Refused"
      title="This question cannot be answered from the governed data"
      lede="The agent fails closed rather than guessing past the semantic boundary."
    >
      <div className="space-y-7">
        {refusal.missing.length > 0 ? (
          <StateField label="What is missing">
            <ul className="space-y-2">
              {refusal.missing.map((item) => (
                <li key={item} className="before:mr-2 before:text-ink-faint before:content-['—']">
                  {item}
                </li>
              ))}
            </ul>
          </StateField>
        ) : null}

        {/* Never populated by the current backend path; shown when it is. */}
        {refusal.closest_answerable ? (
          <div>
            <SectionLabel>Closest answerable question</SectionLabel>
            <button
              type="button"
              onClick={() => onAsk(refusal.closest_answerable ?? '')}
              className="mt-2.5 block w-full rounded-sm border border-hairline-strong bg-surface px-5 py-4 text-left transition-colors duration-micro ease-editorial hover:border-gold hover:bg-[var(--c-gold-wash)]"
            >
              <span className="font-serif text-[1.0625rem] text-ink">
                {refusal.closest_answerable}
              </span>
              <span className="mt-1.5 block text-[0.6875rem] text-ink-faint">
                Ask this instead
              </span>
            </button>
          </div>
        ) : null}
      </div>
    </StateShell>
  );
}

/* ---------- blocked ---------- */

export function BlockedState({ block }: { block: BlockBlock }) {
  return (
    <StateShell
      Icon={ShieldX}
      tone="terracotta"
      eyebrow="Blocked at ingress"
      title="The ingress guard stopped this request"
      lede="Safety is enforced deterministically, before any model or query runs."
    >
      <div className="space-y-7">
        <div>
          <SectionLabel>Reason</SectionLabel>
          <div className="mt-2.5">
            <Tag tone="terracotta">{humanise(block.reason)}</Tag>
          </div>
        </div>
        <StateField label="Detail">{block.detail}</StateField>
      </div>
    </StateShell>
  );
}

/* ---------- insufficient evidence ---------- */

export function InsufficientEvidenceState({
  envelope,
}: {
  envelope: AnswerEnvelope;
}) {
  return (
    <StateShell
      Icon={ScanSearch}
      eyebrow="Insufficient evidence"
      title="Not enough evidence to stand behind an answer"
      lede={
        envelope.conclusion ??
        'The analysis ran, but the evidence was too weak to support a conclusion.'
      }
    >
      {envelope.caveats.length > 0 ? (
        <StateField label="Why">
          <ul className="space-y-2">
            {envelope.caveats.map((caveat) => (
              <li
                key={caveat}
                className="before:mr-2 before:text-ink-faint before:content-['—']"
              >
                {caveat}
              </li>
            ))}
          </ul>
        </StateField>
      ) : null}
    </StateShell>
  );
}

/* ---------- error ---------- */

export function ErrorState({
  detail,
  streamError,
  onRetry,
}: {
  detail: string | null;
  streamError: ErrorEvent['error'] | null;
  onRetry?: (() => void) | undefined;
}) {
  const message = streamError?.message ?? detail;

  return (
    <StateShell
      Icon={TriangleAlert}
      tone="terracotta"
      eyebrow="Error"
      title="The run did not complete"
      lede={message ?? 'The agent service reported a failure while answering.'}
    >
      <div className="flex flex-wrap items-center gap-4">
        {streamError ? (
          <div className="flex flex-wrap gap-2">
            <Tag tone="terracotta">{streamError.code}</Tag>
            <Tag>{streamError.retriable ? 'retriable' : 'not retriable'}</Tag>
          </div>
        ) : null}
        {onRetry && (streamError?.retriable ?? true) ? (
          <Button variant="quiet" onClick={onRetry} className="ml-auto">
            Ask again
          </Button>
        ) : null}
      </div>
    </StateShell>
  );
}

/* ---------- backend offline ---------- */

export function OfflineState({
  detail,
  onRetry,
}: {
  detail: string;
  onRetry?: (() => void) | undefined;
}) {
  return (
    <StateShell
      Icon={CloudOff}
      eyebrow="Service unreachable"
      title="Nothing is answering at /api"
      lede={detail}
    >
      <div className="space-y-6">
        <div>
          <SectionLabel>Start the backend</SectionLabel>
          <Card tone="sunken" className="mt-2.5 p-4">
            <code className="block overflow-x-auto font-mono text-[0.8125rem] text-ink">
              uvicorn app:app --app-dir backend/src --reload
            </code>
          </Card>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <a
            href="?mock=1"
            className="inline-flex items-center rounded-sm border border-gold bg-[var(--c-gold-wash)] px-4 py-2 text-small font-medium text-gold-ink transition-colors duration-micro hover:brightness-105"
          >
            Preview with sample answers
          </a>
          {onRetry ? (
            <Button variant="quiet" onClick={onRetry}>
              Try again
            </Button>
          ) : null}
        </div>
      </div>
    </StateShell>
  );
}
