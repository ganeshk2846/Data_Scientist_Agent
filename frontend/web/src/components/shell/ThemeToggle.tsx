import { Monitor, Moon, Sun } from 'lucide-react';

import { cx } from '@/lib/cx';
import type { ThemeController } from '@/hooks/useTheme';
import type { ThemeSetting } from '@/lib/theme';

const OPTIONS: readonly { value: ThemeSetting; label: string; Icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'dark', label: 'Dark', Icon: Moon },
  { value: 'system', label: 'System', Icon: Monitor },
];

/** A three-position segmented control, defaulting to the system preference. */
export function ThemeToggle({ theme }: { theme: ThemeController }) {
  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex items-center gap-0.5 rounded-sm border border-hairline bg-sunken p-0.5"
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = theme.setting === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            onClick={() => theme.set(value)}
            className={cx(
              'rounded-sm p-1.5 transition-colors duration-micro ease-editorial',
              active
                ? 'bg-surface text-ink shadow-soft'
                : 'text-ink-faint hover:text-ink-muted',
            )}
          >
            <Icon size={14} strokeWidth={1.5} aria-hidden />
          </button>
        );
      })}
    </div>
  );
}
