/**
 * Local persistence.
 *
 * Everything this product remembers is remembered *locally*, in this browser,
 * and every surface that shows remembered data says so. The backend keeps runs
 * in a process-local store, so there is no server-side history to read back;
 * what the rail, the pinboard and compare mode show is this machine's own
 * record of what it asked.
 *
 * Every accessor is total: a private window, blocked site data and a quota
 * failure all land in the same place, and the caller gets the fallback rather
 * than an exception. A remembered preference is a convenience, never a
 * requirement.
 */

const PREFIX = 'ds-agent';

export const KEYS = {
  theme: `${PREFIX}-theme`,
  accent: `${PREFIX}-accent`,
  density: `${PREFIX}-density`,
  motion: `${PREFIX}-motion`,
  history: `${PREFIX}-history`,
  pins: `${PREFIX}-pins`,
  tour: `${PREFIX}-tour-seen`,
} as const;

export function readRaw(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeRaw(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Quota, private mode, or blocked site data. Nothing here is required.
  }
}

export function removeRaw(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // As above.
  }
}

/**
 * Reads JSON through a validator. The validator is the whole point: stored
 * data is from an *older build of this app*, which makes it as untrustworthy
 * as anything off the wire. Anything that does not validate is discarded.
 */
export function readJson<T>(key: string, validate: (value: unknown) => T | null): T | null {
  const raw = readRaw(key);
  if (raw === null) return null;
  try {
    return validate(JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

export function writeJson(key: string, value: unknown): void {
  try {
    writeRaw(key, JSON.stringify(value));
  } catch {
    // A value with a cycle in it; not worth failing a render over.
  }
}

/** True when `value` is a plain object — the guard every validator starts with. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
