/**
 * The Theme Atelier: accent variant, density and motion.
 *
 * All three are stamped as attributes on `<html>` — `data-accent`,
 * `data-density`, `data-motion` — because that is where `index.css` keys its
 * token blocks. Nothing is passed down through React; a setting change is one
 * attribute write and the whole product re-tones.
 */

import { KEYS, readRaw, writeRaw } from './storage';

export type Accent = 'champagne' | 'platinum' | 'bronze';
export type Density = 'comfortable' | 'compact';
export type MotionSetting = 'full' | 'reduced';

export interface Settings {
  accent: Accent;
  density: Density;
  motion: MotionSetting;
}

export const DEFAULT_SETTINGS: Settings = {
  accent: 'champagne',
  density: 'comfortable',
  motion: 'full',
};

export const ACCENTS: readonly { value: Accent; label: string; note: string }[] = [
  { value: 'champagne', label: 'Champagne Gold', note: 'The house accent' },
  { value: 'platinum', label: 'Platinum', note: 'Cool silver-grey' },
  { value: 'bronze', label: 'Bronze', note: 'Warm copper' },
];

export const DENSITIES: readonly { value: Density; label: string; note: string }[] = [
  { value: 'comfortable', label: 'Comfortable', note: 'Full air between sections' },
  { value: 'compact', label: 'Compact', note: 'The same composition, tighter' },
];

export const MOTIONS: readonly { value: MotionSetting; label: string; note: string }[] = [
  { value: 'full', label: 'Full', note: 'Reveals, traces and travelling light' },
  { value: 'reduced', label: 'Reduced', note: 'Nothing moves but the data' },
];

function isAccent(value: string | null): value is Accent {
  return value === 'champagne' || value === 'platinum' || value === 'bronze';
}

function isDensity(value: string | null): value is Density {
  return value === 'comfortable' || value === 'compact';
}

function isMotion(value: string | null): value is MotionSetting {
  return value === 'full' || value === 'reduced';
}

export function readSettings(): Settings {
  const accent = readRaw(KEYS.accent);
  const density = readRaw(KEYS.density);
  const motion = readRaw(KEYS.motion);
  return {
    accent: isAccent(accent) ? accent : DEFAULT_SETTINGS.accent,
    density: isDensity(density) ? density : DEFAULT_SETTINGS.density,
    motion: isMotion(motion) ? motion : DEFAULT_SETTINGS.motion,
  };
}

export function storeSettings(settings: Settings): void {
  writeRaw(KEYS.accent, settings.accent);
  writeRaw(KEYS.density, settings.density);
  writeRaw(KEYS.motion, settings.motion);
}

/**
 * Stamps the settings on the document. `data-motion` is only written for the
 * reduced case: an absent attribute means "whatever the OS asked for", so a
 * reader who set `prefers-reduced-motion` is never overridden by our default.
 */
export function applySettings(settings: Settings): void {
  const root = document.documentElement;
  root.setAttribute('data-accent', settings.accent);
  root.setAttribute('data-density', settings.density);
  if (settings.motion === 'reduced') root.setAttribute('data-motion', 'reduced');
  else root.removeAttribute('data-motion');
}
