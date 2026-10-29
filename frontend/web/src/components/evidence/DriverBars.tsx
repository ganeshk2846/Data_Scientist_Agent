import { Tag } from '@/components/briefing/StatusBadge';
import { cx } from '@/lib/cx';
import { formatNumber, formatPercent, formatSigned } from '@/lib/format';
import { sortDrivers } from '@/lib/evidence';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import type { DriverContribution, DriverResult } from '@/types/envelope';

/**
 * Additive contributions as horizontal bars around a shared zero line: sage for
 * positive, terracotta for negative, interval whiskers for the approximate
 * bounds, sorted by magnitude, and unstable rows dimmed.
 */
export function DriverBars({ result }: { result: DriverResult }) {
  const reduced = useReducedMotion();
  const drivers = sortDrivers(result);

  if (drivers.length === 0) {
    return (
      <p className="text-small text-ink-muted">
        The driver module examined{' '}
        <span className="tabular-nums">{formatNumber(result.candidates_examined)}</span>{' '}
        candidates and found no contribution worth reporting.
      </p>
    );
  }

  // One shared scale across contributions and their intervals, so whiskers
  // cannot overflow their bar.
  const extent = Math.max(
    ...drivers.flatMap((driver) => [
      Math.abs(driver.contribution),
      Math.abs(driver.interval[0]),
      Math.abs(driver.interval[1]),
    ]),
    Math.abs(result.total_change) * 0.0001,
  );
  const scale = (value: number) => (extent === 0 ? 0 : (value / extent) * 50);

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div>
          <div className="text-micro uppercase text-ink-faint">
            {result.metric} · {result.current_period} against {result.comparison_period}
          </div>
          <div className="mt-1.5 flex items-baseline gap-3">
            <span
              className={cx(
                'font-serif text-figure tabular-nums',
                result.total_change < 0 ? 'text-terracotta' : 'text-sage',
              )}
            >
              {formatSigned(result.total_change)}
            </span>
            <span className="text-small text-ink-faint">total change</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Tag title="Rows the attribution could not account for">
            {formatNumber(result.reconciliation_error, 2)} unexplained
          </Tag>
          <Tag>{formatNumber(result.candidates_examined)} examined</Tag>
        </div>
      </div>

      <ul className="mt-7 space-y-4">
        {drivers.map((driver, index) => (
          <DriverRow
            key={`${driver.dimension}:${driver.value}`}
            driver={driver}
            scale={scale}
            delay={reduced ? 0 : index * 0.06}
            reduced={reduced}
          />
        ))}
      </ul>

      {/* The zero line is the reference the bars read against. */}
      <div className="relative mt-5 h-4">
        <div aria-hidden className="absolute left-1/2 top-0 h-2 w-px bg-hairline-strong" />
        <div className="absolute left-1/2 top-2.5 -translate-x-1/2 text-[0.6875rem] text-ink-faint">
          0
        </div>
      </div>
    </div>
  );
}

function DriverRow({
  driver,
  scale,
  delay,
  reduced,
}: {
  driver: DriverContribution;
  scale: (value: number) => number;
  delay: number;
  reduced: boolean;
}) {
  const negative = driver.contribution < 0;
  const width = Math.abs(scale(driver.contribution));
  const [low, high] = driver.interval;
  const whiskerFrom = Math.min(scale(low), scale(high));
  const whiskerTo = Math.max(scale(low), scale(high));

  return (
    <li className={cx('group/driver', driver.unstable && 'opacity-55')}>
      <div className="flex items-baseline justify-between gap-4">
        <div className="min-w-0">
          <span className="text-small text-ink">{driver.value}</span>
          <span className="ml-2 text-[0.6875rem] uppercase text-ink-faint">
            {driver.dimension}
          </span>
        </div>
        <div className="flex shrink-0 items-baseline gap-3">
          <span
            className={cx(
              'text-small tabular-nums',
              negative ? 'text-terracotta' : 'text-sage',
            )}
          >
            {formatSigned(driver.contribution)}
          </span>
          <span className="w-12 text-right text-[0.6875rem] tabular-nums text-ink-faint">
            {formatPercent(driver.share * 100)}
          </span>
        </div>
      </div>

      <div className="relative mt-2 h-5">
        <div aria-hidden className="absolute inset-x-0 top-2.5 h-px bg-hairline" />
        <div aria-hidden className="absolute left-1/2 inset-y-0 w-px bg-hairline-strong" />

        {/* The interval, behind the bar. */}
        <div
          aria-hidden
          className={cx(
            'absolute top-[0.5625rem] h-1 rounded-full',
            negative ? 'bg-terracotta/25' : 'bg-sage/25',
          )}
          style={{
            left: `${50 + whiskerFrom}%`,
            width: `${Math.max(0.3, whiskerTo - whiskerFrom)}%`,
          }}
        />
        {[whiskerFrom, whiskerTo].map((position, index) => (
          <div
            key={index}
            aria-hidden
            className={cx(
              'absolute top-[0.1875rem] h-3.5 w-px',
              negative ? 'bg-terracotta/60' : 'bg-sage/60',
            )}
            style={{ left: `${50 + position}%` }}
          />
        ))}

        {/* The contribution bar. */}
        <div
          aria-hidden
          className={cx(
            'absolute top-[0.4375rem] h-1.5 rounded-sm',
            negative ? 'bg-terracotta' : 'bg-sage',
            !reduced && 'transition-[width] duration-draw ease-editorial',
          )}
          style={{
            left: negative ? `${50 - width}%` : '50%',
            width: `${width}%`,
            transitionDelay: `${delay}s`,
          }}
        />
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.6875rem] text-ink-faint">
        <span className="tabular-nums">
          interval {formatSigned(low)} to {formatSigned(high)}
        </span>
        <span className="tabular-nums">n = {formatNumber(driver.sample_size)}</span>
        <span>grade {driver.grade}</span>
        {driver.unstable ? <span className="text-terracotta">unstable</span> : null}
      </div>

      {driver.unstable && driver.data_needed_to_strengthen.length > 0 ? (
        <p className="mt-1 text-[0.6875rem] leading-relaxed text-ink-faint">
          To strengthen: {driver.data_needed_to_strengthen.join('; ')}
        </p>
      ) : null}
    </li>
  );
}
