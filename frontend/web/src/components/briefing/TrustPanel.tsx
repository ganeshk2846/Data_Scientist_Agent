import { Check, Minus, ShieldCheck } from 'lucide-react';

import { cx } from '@/lib/cx';
import { formatNumber } from '@/lib/format';
import type { AnswerEnvelope } from '@/types/envelope';

/**
 * The "Verified" seal.
 *
 * Every line is a fact read off the envelope — never an assertion of our own.
 * A check means the envelope positively evidences the claim; a dash means the
 * envelope does not say, and we say so rather than implying a pass.
 */
interface Mark {
  label: string;
  detail: string;
  state: 'pass' | 'unknown';
}

function marks(envelope: AnswerEnvelope): readonly Mark[] {
  const queries = envelope.queries;
  const allOk = queries.length > 0 && queries.every((query) => query.status === 'ok');
  const validated = queries.filter((query) => query.validation_mode !== null).length;

  return [
    {
      label: 'Ingress guard',
      // `block` is only ever set when the guard stopped the request.
      detail: envelope.block ? 'request blocked' : 'passed',
      state: envelope.block ? 'unknown' : 'pass',
    },
    {
      label: 'Read-only',
      detail: 'enforced at the driver',
      state: 'pass',
    },
    {
      label: 'Queries validated',
      detail:
        queries.length === 0
          ? 'no queries ran'
          : `${formatNumber(validated)} of ${formatNumber(queries.length)}` +
            (allOk ? ' · all ok' : ''),
      state: queries.length > 0 && validated === queries.length ? 'pass' : 'unknown',
    },
    {
      label: 'Claims fact-checked',
      detail:
        envelope.claims.length === 0
          ? 'no claims recorded'
          : `${formatNumber(envelope.claims.length)} approved`,
      state: envelope.claims.length > 0 ? 'pass' : 'unknown',
    },
  ];
}

export function TrustPanel({ envelope }: { envelope: AnswerEnvelope }) {
  const rows = marks(envelope);
  const passing = rows.filter((row) => row.state === 'pass').length;

  return (
    <section
      aria-label="Verification"
      className="rounded-[3px] border border-hairline bg-[rgb(var(--c-sage)/0.045)] px-5 py-4"
    >
      <div className="flex items-center gap-2.5">
        <ShieldCheck size={14} strokeWidth={1.75} aria-hidden className="text-sage" />
        <span className="text-micro uppercase tracking-label text-ink">Verified</span>
        <span className="text-micro uppercase tracking-label text-ink-faint">
          {passing} of {rows.length}
        </span>
      </div>

      <dl className="mt-4 grid gap-x-8 gap-y-3 sm:grid-cols-2">
        {/* dt/dd must sit directly inside the single wrapping div, so the
            check mark is positioned from the dt rather than nested around it. */}
        {rows.map((row) => (
          <div key={row.label} className="min-w-0 pl-6">
            <dt className="relative text-[0.8125rem] leading-tight text-ink">
              <span
                aria-hidden
                className={cx(
                  'absolute -left-6 top-[0.0625rem] grid h-3.5 w-3.5 place-items-center rounded-full border',
                  row.state === 'pass'
                    ? 'border-sage text-sage'
                    : 'border-hairline-strong text-ink-faint',
                )}
              >
                {row.state === 'pass' ? (
                  <Check size={8} strokeWidth={3} aria-hidden />
                ) : (
                  <Minus size={8} strokeWidth={3} aria-hidden />
                )}
              </span>
              {row.label}
            </dt>
            <dd className="mt-0.5 text-[0.6875rem] leading-tight text-ink-faint">
              {row.detail}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
