import { cx } from '@/lib/cx';

/**
 * A segmented picker: one row, one choice, a hairline frame.
 *
 * The selection is carried by a wash and a hairline, never by a filled block of
 * accent — the accent belongs to the single focal element on a screen, and a
 * row of pickers is not it. The whole row is one radiogroup, so the arrow keys
 * work the way a reader expects without any key handling of our own.
 */

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  /** A second line, for a picker that needs explaining. */
  note?: string;
  disabled?: boolean;
  /** Said instead of the label when the control needs more than the label. */
  title?: string;
}

interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: readonly SegmentedOption<T>[];
  onChange: (value: T) => void;
  /** `stack` gives each option its own row, for options with notes. */
  layout?: 'row' | 'stack';
  className?: string;
}

export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  layout = 'row',
  className,
}: SegmentedProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cx(
        'rounded-sm border border-hairline bg-sunken p-0.5',
        layout === 'row' ? 'inline-flex gap-0.5' : 'flex flex-col gap-0.5',
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={option.disabled}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cx(
              'rounded-sm px-3 py-1.5 text-left transition-colors duration-hover ease-editorial',
              layout === 'row' ? 'text-center' : 'w-full',
              option.disabled && 'cursor-not-allowed opacity-45',
              active
                ? 'bg-[rgb(var(--c-surface))] shadow-soft'
                : 'hover:bg-[rgb(var(--c-hairline)/0.45)]',
            )}
          >
            <span
              className={cx(
                'block text-[0.8125rem] leading-5',
                active ? 'text-ink' : 'text-ink-muted',
              )}
            >
              {option.label}
            </span>
            {option.note ? (
              <span className="mt-px block text-[0.6875rem] leading-4 text-ink-faint">
                {option.note}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
