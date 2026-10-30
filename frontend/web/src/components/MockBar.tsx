import { FlaskConical } from 'lucide-react';

import { STATUS_LABEL } from '@/components/briefing/StatusBadge';
import { Card, SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import { MOCK_SCENARIOS } from '@/lib/mock/envelopes';
import { V2_SCENARIOS } from '@/lib/mock/v2';

/**
 * Only rendered under `?mock=1`. Every scenario is one click away, so each
 * designed status can be reviewed without a backend and without guessing which
 * phrasing routes where.
 */
export function MockBar({
  onPick,
  activeQuestion,
}: {
  onPick: (question: string) => void;
  activeQuestion: string | null;
}) {
  return (
    <Card tone="sunken" className="p-5">
      <div className="flex items-center gap-2">
        <FlaskConical size={13} strokeWidth={1.5} aria-hidden className="text-accent" />
        <SectionLabel>Mock mode · every status</SectionLabel>
      </div>

      <ul className="mt-4 flex flex-wrap gap-2">
        {MOCK_SCENARIOS.map((scenario) => {
          const active = activeQuestion === scenario.question;
          return (
            <li key={scenario.id}>
              <button
                type="button"
                onClick={() => onPick(scenario.question)}
                title={scenario.question}
                className={cx(
                  'rounded-sm border px-3.5 py-1.5 text-[0.6875rem]',
                  'transition-colors duration-micro ease-editorial',
                  active
                    ? 'border-accent bg-[var(--c-accent-wash)] text-accent-ink'
                    : 'border-hairline-strong text-ink-muted hover:border-hairline-strong hover:text-ink',
                )}
              >
                <span className="uppercase tracking-wide">
                  {STATUS_LABEL[scenario.status]}
                </span>
                {scenario.status === 'answered' ? (
                  <span className="ml-1.5 normal-case tracking-normal text-ink-faint">
                    {scenario.id}
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>

      {/* V2: every intent, a follow-up and the clarification flow. Labelled by
          intent only, so no chip here repeats a V1 status word. */}
      <SectionLabel className="mt-5">V2 · every intent</SectionLabel>
      <ul className="mt-3 flex flex-wrap gap-2">
        {V2_SCENARIOS.map((scenario) => {
          const active = activeQuestion === scenario.question;
          return (
            <li key={scenario.id}>
              <button
                type="button"
                onClick={() => onPick(scenario.question)}
                title={scenario.question}
                className={cx(
                  'rounded-sm border px-3.5 py-1.5 text-[0.6875rem]',
                  'transition-colors duration-micro ease-editorial',
                  active
                    ? 'border-accent bg-[var(--c-accent-wash)] text-accent-ink'
                    : 'border-hairline-strong text-ink-muted hover:text-ink',
                )}
              >
                {scenario.label}
              </button>
            </li>
          );
        })}
      </ul>

      <p className="mt-4 max-w-prose text-[0.6875rem] leading-relaxed text-ink-faint">
        V2 samples were captured from the real V2 pipeline on the synthetic test
        fixture, so their figures are the fixture's. Sample envelopes only. They are contract-accurate, and are the one place
        next_actions and refusal.closest_answerable are populated — the live backend
        never sets either.
      </p>
    </Card>
  );
}
