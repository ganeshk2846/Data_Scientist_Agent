import { useCallback, useEffect, useState } from 'react';

import {
  applyTheme,
  readStoredSetting,
  resolveTheme,
  storeSetting,
  watchSystemTheme,
  type ResolvedTheme,
  type ThemeSetting,
} from '@/lib/theme';

export interface ThemeController {
  setting: ThemeSetting;
  resolved: ResolvedTheme;
  /** Cycles light → dark → system. */
  cycle: () => void;
  set: (setting: ThemeSetting) => void;
}

const ORDER: readonly ThemeSetting[] = ['light', 'dark', 'system'];

export function useTheme(): ThemeController {
  const [setting, setSetting] = useState<ThemeSetting>(() => readStoredSetting());
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    resolveTheme(readStoredSetting()),
  );

  useEffect(() => {
    const next = resolveTheme(setting);
    setResolved(next);
    applyTheme(next);
  }, [setting]);

  // Only follow the OS while the setting is "system".
  useEffect(() => {
    if (setting !== 'system') return;
    return watchSystemTheme((theme) => {
      setResolved(theme);
      applyTheme(theme);
    });
  }, [setting]);

  const set = useCallback((next: ThemeSetting) => {
    setSetting(next);
    storeSetting(next);
  }, []);

  const cycle = useCallback(() => {
    setSetting((current) => {
      const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length] ?? 'system';
      storeSetting(next);
      return next;
    });
  }, []);

  return { setting, resolved, cycle, set };
}
