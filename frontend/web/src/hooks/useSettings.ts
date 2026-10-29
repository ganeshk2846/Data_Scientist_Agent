import { useCallback, useEffect, useState } from 'react';

import {
  applySettings,
  readSettings,
  storeSettings,
  type Accent,
  type Density,
  type MotionSetting,
  type Settings,
} from '@/lib/settings';

export interface SettingsController extends Settings {
  setAccent: (accent: Accent) => void;
  setDensity: (density: Density) => void;
  setMotion: (motion: MotionSetting) => void;
}

/**
 * The Atelier's state. The settings are stamped on `<html>` in an effect rather
 * than threaded through components — see `lib/settings.ts`.
 */
export function useSettings(): SettingsController {
  const [settings, setSettings] = useState<Settings>(readSettings);

  useEffect(() => {
    applySettings(settings);
    storeSettings(settings);
  }, [settings]);

  const setAccent = useCallback(
    (accent: Accent) => setSettings((current) => ({ ...current, accent })),
    [],
  );
  const setDensity = useCallback(
    (density: Density) => setSettings((current) => ({ ...current, density })),
    [],
  );
  const setMotion = useCallback(
    (motion: MotionSetting) => setSettings((current) => ({ ...current, motion })),
    [],
  );

  return { ...settings, setAccent, setDensity, setMotion };
}
