/**
 * Theme state. Three settings — light, dark, or follow the system — with the
 * system preference as the default. The resolved theme is stamped on
 * `<html data-theme>`, which is what `index.css` keys its token blocks on.
 */

export type ThemeSetting = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'ds-agent-theme';

function systemTheme(): ResolvedTheme {
  if (typeof window === 'undefined' || !window.matchMedia) return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function readStoredSetting(): ThemeSetting {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  } catch {
    // Private windows and blocked site data both land here; fall through.
  }
  return 'system';
}

export function storeSetting(setting: ThemeSetting): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, setting);
  } catch {
    // A remembered theme is a convenience, never a requirement.
  }
}

export function resolveTheme(setting: ThemeSetting): ResolvedTheme {
  return setting === 'system' ? systemTheme() : setting;
}

export function applyTheme(resolved: ResolvedTheme): void {
  document.documentElement.setAttribute('data-theme', resolved);
}

/** Calls back whenever the OS preference flips. Returns an unsubscribe. */
export function watchSystemTheme(onChange: (theme: ResolvedTheme) => void): () => void {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {};
  const query = window.matchMedia('(prefers-color-scheme: dark)');
  const handler = (event: MediaQueryListEvent) => onChange(event.matches ? 'dark' : 'light');
  query.addEventListener('change', handler);
  return () => query.removeEventListener('change', handler);
}
