import { Settings2 } from 'lucide-react';
import { useState } from 'react';

import { Popover } from '@/components/ui/Popover';
import { Segmented } from '@/components/ui/Segmented';
import { Hairline, SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import { ACCENTS, DENSITIES, MOTIONS } from '@/lib/settings';
import type { SettingsController } from '@/hooks/useSettings';

/**
 * The Theme Atelier.
 *
 * Three dials — accent, density, motion — plus the two housekeeping actions
 * that belong with them: replay the tour, and forget the locally stored
 * history. The accent swatches are the one place in the product where all three
 * accents are visible at once, so each is drawn as an actual sample of its own
 * token rather than described in words.
 */
export function SettingsPopover({
  settings,
  historyCount,
  onReplayTour,
  onClearHistory,
}: {
  settings: SettingsController;
  historyCount: number;
  onReplayTour: () => void;
  onClearHistory: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        title="Settings — accent, density, motion"
        className={cx(
          'rounded-sm p-1.5 transition-colors duration-hover ease-editorial',
          open ? 'text-ink' : 'text-ink-faint hover:text-ink',
        )}
      >
        <Settings2 size={16} strokeWidth={1.5} aria-hidden />
        <span className="sr-only">Settings</span>
      </button>

      <Popover
        open={open}
        onClose={() => setOpen(false)}
        placement="bottom"
        align="right"
        width="min(20rem, calc(100vw - 2rem))"
        label="Settings"
      >
        <SectionLabel>Accent</SectionLabel>
        <div role="radiogroup" aria-label="Accent" className="mt-3 space-y-0.5">
          {ACCENTS.map((option) => {
            const active = settings.accent === option.value;
            return (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => settings.setAccent(option.value)}
                className={cx(
                  'flex w-full items-center gap-3 rounded-sm px-2 py-2 text-left',
                  'transition-colors duration-hover ease-editorial',
                  active ? 'bg-[var(--c-accent-wash)]' : 'hover:bg-[rgb(var(--c-hairline)/0.45)]',
                )}
              >
                {/* Each swatch paints its own variant's token, so the choice is
                    shown rather than described. */}
                <span
                  aria-hidden
                  data-accent={option.value}
                  className={cx(
                    'h-5 w-5 shrink-0 rounded-full bg-accent',
                    active
                      ? 'ring-1 ring-accent ring-offset-2 ring-offset-[rgb(var(--c-surface-high))]'
                      : '',
                  )}
                />
                <span className="min-w-0 flex-1">
                  <span
                    className={cx(
                      'block text-[0.8125rem] leading-5',
                      active ? 'text-ink' : 'text-ink-muted',
                    )}
                  >
                    {option.label}
                  </span>
                  <span className="block text-[0.6875rem] leading-4 text-ink-faint">
                    {option.note}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        <Hairline className="my-4" />

        <SectionLabel>Density</SectionLabel>
        <Segmented
          label="Density"
          value={settings.density}
          options={DENSITIES}
          onChange={settings.setDensity}
          layout="stack"
          className="mt-3 w-full"
        />

        <Hairline className="my-4" />

        <SectionLabel>Motion</SectionLabel>
        <Segmented
          label="Motion"
          value={settings.motion}
          options={MOTIONS}
          onChange={settings.setMotion}
          layout="stack"
          className="mt-3 w-full"
        />

        <Hairline className="my-4" />

        <div className="space-y-2">
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onReplayTour();
            }}
            className="w-full rounded-sm px-2 py-1.5 text-left text-[0.8125rem] text-ink-muted transition-colors duration-hover ease-editorial hover:bg-[rgb(var(--c-hairline)/0.45)] hover:text-ink"
          >
            Replay the tour
          </button>
          <button
            type="button"
            onClick={onClearHistory}
            disabled={historyCount === 0}
            className="w-full rounded-sm px-2 py-1.5 text-left text-[0.8125rem] text-ink-muted transition-colors duration-hover ease-editorial hover:bg-[rgb(var(--c-hairline)/0.45)] hover:text-ink disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
          >
            Forget stored history
            <span className="ml-1.5 tabular-nums text-ink-faint">({historyCount})</span>
          </button>
          <p className="px-2 pt-1 text-[0.6875rem] leading-4 text-ink-faint">
            History and pins are stored in this browser only. Nothing is sent
            anywhere.
          </p>
        </div>
      </Popover>
    </div>
  );
}
