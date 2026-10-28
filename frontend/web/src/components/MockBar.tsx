import { FlaskConical } from 'lucide-react';

import { STATUS_LABEL } from '@/components/briefing/StatusBadge';
import { Card, SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import { MOCK_SCENARIOS } from '@/lib/mock/envelopes';

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
        <FlaskConical size={13} strokeWidth={1.75} aria-hidden className="text-gold" />
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
                  'rounded-full border px-3.5 py-1.5 text-[0.6875rem]',
                  'transition-colors duration-micro ease-editorial',
                  active
                    ? 'border-gold bg-[var(--c-gold-wash)] text-gold'
                    : 'border-hairline-strong text-ink-muted hover:border-gold hover:text-ink',
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

      <p className="mt-4 max-w-prose text-[0.6875rem] leading-relaxed text-ink-faint">
        Sample envelopes only. They are contract-accurate, and are the one place
        next_actions and refusal.closest_answerable are populated — the live backend
        never sets either.
      </p>
    </Card>
  );
}
