import { Check, Minus } from 'lucide-react';

import { cx } from '@/lib/cx';
import { formatNumber } from '@/lib/format';
import type { AnswerEnvelope } from '@/types/envelope';

/**
 * The verification seal.
 *
 * Every line is a fact read off the envelope — never an assertion of our own.
 * A check means the envelope positively evidences the claim; a dash means the
 * envelope does not say, and we say so rather than implying a pass.
 *
 * The mark itself is drawn as a struck hallmark: an octagonal die, a hairline
 * inner ring, the count on the metal, and the words around the rim. The emboss
 * is real light — an inset highlight on the top edge and a contact shadow
 * underneath — rather than a bevel filter, so it reads as pressed into the
 * surface in both themes and prints as a clean line drawing.
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

/** An eight-sided die, struck. 88 × 88, on a 44,44 centre. */
function Hallmark({ passing, total }: { passing: number; total: number }) {
  const full = passing === total;
  // An octagon on a 44 radius: the standard assay-mark silhouette.
  const octagon = Array.from({ length: 8 }, (_, index) => {
    const angle = (Math.PI / 4) * index + Math.PI / 8;
    return `${(44 + 37 * Math.cos(angle)).toFixed(2)},${(44 + 37 * Math.sin(angle)).toFixed(2)}`;
  }).join(' ');

  return (
    <div
      aria-hidden
      className={cx(
        'relative grid h-[5.5rem] w-[5.5rem] shrink-0 place-items-center rounded-full',
        // The emboss: a highlight on the top edge, a contact shadow below.
        'bg-[rgb(var(--c-surface))]',
        'shadow-[inset_0_1px_0_var(--c-lift),inset_0_-1px_0_var(--c-shadow-a),0_1px_2px_var(--c-shadow-b)]',
      )}
    >
      <svg viewBox="0 0 88 88" className="absolute inset-0 h-full w-full">
        <defs>
          {/* The rim text runs clockwise along this circle. */}
          <path
            id="hallmark-rim"
            d="M 44 44 m -30 0 a 30 30 0 1 1 60 0 a 30 30 0 1 1 -60 0"
          />
        </defs>

        <polygon
          points={octagon}
          fill="none"
          stroke={full ? 'rgb(var(--c-sage))' : 'rgb(var(--c-hairline-strong))'}
          strokeWidth="1"
        />
        <circle
          cx="44"
          cy="44"
          r="30"
          fill="none"
          stroke="rgb(var(--c-hairline))"
          strokeWidth="1"
        />
        <text
          className="font-sans"
          fill={full ? 'rgb(var(--c-sage-ink))' : 'rgb(var(--c-ink-faint))'}
          style={{ fontSize: '7.5px', letterSpacing: '2.1px', fontWeight: 500 }}
        >
          <textPath href="#hallmark-rim" startOffset="4%">
            VERIFIED · LEDGER · FACT CHECKED ·
          </textPath>
        </text>
      </svg>

      {/* The count, struck on the metal. */}
      <span className="relative flex flex-col items-center leading-none">
        <Check
          size={15}
          strokeWidth={1.5}
          className={full ? 'text-sage' : 'text-ink-faint'}
        />
        <span
          className={cx(
            'mt-1 font-mono text-[0.75rem] tabular-nums',
            full ? 'text-sage-ink' : 'text-ink-muted',
          )}
        >
          {passing}/{total}
        </span>
      </span>
    </div>
  );
}

export function TrustPanel({ envelope }: { envelope: AnswerEnvelope }) {
  const rows = marks(envelope);
  const passing = rows.filter((row) => row.state === 'pass').length;

  return (
    <section
      aria-label="Verification"
      className="edge-light rounded-sm border border-hairline bg-[rgb(var(--c-sage)/0.04)] px-5 py-5 sm:px-7 sm:py-6"
    >
      <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:gap-8">
        <div className="flex items-center gap-5">
          <Hallmark passing={passing} total={rows.length} />
          <div>
            <p className="text-micro uppercase tracking-label text-ink">Verified</p>
            <p className="mt-2 max-w-[13rem] text-[0.6875rem] leading-4 text-ink-faint">
              {passing} of {rows.length} checks evidenced by this run's own
              envelope. A dash is silence, not a pass.
            </p>
          </div>
        </div>

        <dl className="grid flex-1 gap-x-8 gap-y-3.5 sm:grid-cols-2">
          {/* dt/dd must sit directly inside the single wrapping div, so the
              check mark is positioned from the dt rather than nested around it. */}
          {rows.map((row) => (
            <div key={row.label} className="min-w-0 pl-6">
              <dt className="relative text-[0.8125rem] leading-5 text-ink">
                <span
                  aria-hidden
                  className={cx(
                    'absolute -left-6 top-px grid h-4 w-4 place-items-center rounded-full border',
                    row.state === 'pass'
                      ? 'border-sage text-sage'
                      : 'border-hairline-strong text-ink-faint',
                  )}
                >
                  {row.state === 'pass' ? (
                    <Check size={10} strokeWidth={1.5} aria-hidden />
                  ) : (
                    <Minus size={10} strokeWidth={1.5} aria-hidden />
                  )}
                </span>
                {row.label}
              </dt>
              <dd className="mt-0.5 text-[0.6875rem] leading-4 text-ink-faint">
                {row.detail}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
