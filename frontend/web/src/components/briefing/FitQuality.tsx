import { Tag } from './StatusBadge';
import { SectionLabel } from '@/components/ui/Card';
import { asAnalystOutput, asLookup } from '@/lib/evidence';
import { findClaim } from '@/lib/v2';
import type { AnswerEnvelope } from '@/types/envelope';

interface Fit {
  method: string | null;
  fallbackReason: string | null;
}

/**
 * Locates the forecast's method and fallback reason: on a live engine output
 * they are `result.method` / `result.method_fallback_reason`; on the
 * precomputed forecast table they are the `model` / `model_fallback_reason`
 * cells of its rows. Located, never inferred.
 */
function readFit(envelope: AnswerEnvelope): Fit {
  for (const block of envelope.evidence) {
    const analyst = asAnalystOutput(block);
    const result = analyst?.result as Record<string, unknown> | null | undefined;
    if (analyst && (analyst.module as string) === 'forecast' && result) {
      return {
        method: typeof result['method'] === 'string' ? result['method'] : null,
        fallbackReason:
          typeof result['method_fallback_reason'] === 'string' ? result['method_fallback_reason'] : null,
      };
    }
    const lookup = asLookup(block);
    if (lookup) {
      const names = lookup.columns.map((column) => column.name);
      const model = names.indexOf('model');
      if (model >= 0 && names.includes('yhat') && lookup.rows[0]) {
        const reason = names.indexOf('model_fallback_reason');
        const row = lookup.rows[0];
        return {
          method: typeof row[model] === 'string' ? (row[model] as string) : null,
          fallbackReason: reason >= 0 && typeof row[reason] === 'string' ? (row[reason] as string) : null,
        };
      }
    }
  }
  return { method: null, fallbackReason: null };
}

/**
 * Method, fallback reason and backtest MAPE (TR-8, AT-4, build-plan 5.12).
 * The MAPE is the ledger claim the backend wrote, shown verbatim; with no such
 * claim it reads "not backtested" — never 0.
 */
export function FitQuality({ envelope }: { envelope: AnswerEnvelope }) {
  const fit = readFit(envelope);
  const mape = findClaim(envelope.claims, /\bMAPE\b/);
  return (
    <div data-testid="fit-quality">
      <SectionLabel>Model and backtest</SectionLabel>
      <dl className="mt-3 grid gap-x-8 gap-y-3 sm:grid-cols-[auto_1fr]">
        <dt className="text-[0.75rem] text-ink-faint">Method</dt>
        <dd className="flex flex-wrap items-center gap-2 text-small text-ink">
          {fit.method ? <Tag>{fit.method}</Tag> : <span className="text-ink-muted">not stated</span>}
          {fit.fallbackReason ? (
            <span className="text-[0.8125rem] text-ink-muted">Fallback: {fit.fallbackReason}</span>
          ) : null}
        </dd>
        <dt className="text-[0.75rem] text-ink-faint">Backtest</dt>
        <dd className="text-small text-ink">
          {mape ? (
            <>
              {mape.text} <span className="font-mono text-[0.6875rem] text-ink-faint">{mape.claim_id}</span>
            </>
          ) : (
            <span className="text-ink-muted">not backtested</span>
          )}
        </dd>
      </dl>
    </div>
  );
}
