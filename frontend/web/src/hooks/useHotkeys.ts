import { useEffect } from 'react';

/** True when focus is in a field, where a bare letter means typing. */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    target.isContentEditable
  );
}

/** A letter is a letter; `?` and `,` are produced differently per layout. */
function isLetter(key: string): boolean {
  return key.length === 1 && /[a-z]/.test(key);
}

interface HotkeyOptions {
  /** Require Shift. Only meaningful for letters. */
  shift?: boolean;
  /** Set false to suspend the binding without unmounting the component. */
  enabled?: boolean;
}

/**
 * A bare single-key shortcut.
 *
 * Ignored while typing, and ignored with Meta/Ctrl/Alt held, so it never
 * fights the browser's own shortcuts. Shift is matched exactly for letters —
 * `S` stars and `⇧P` pins, and neither fires for the other — but is left
 * unchecked for symbol keys, where the layout decides whether Shift is
 * involved in producing `?` at all.
 */
export function useHotkey(
  key: string,
  onFire: () => void,
  options: HotkeyOptions = {},
): void {
  const { shift = false, enabled = true } = options;

  useEffect(() => {
    if (!enabled) return;
    const handler = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const pressed = event.key.toLowerCase();
      if (pressed !== key) return;
      if (isLetter(key) && event.shiftKey !== shift) return;
      if (isTyping(event.target)) return;
      event.preventDefault();
      onFire();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [enabled, key, onFire, shift]);
}

/** Ctrl/Cmd+K opens the command palette. */
export function useAskHotkey(onOpenPalette: () => void): void {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== 'k') return;
      if (!event.metaKey && !event.ctrlKey) return;
      event.preventDefault();
      onOpenPalette();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onOpenPalette]);
}

/** Calls back on Escape, while `active`. */
export function useEscape(active: boolean, onEscape: () => void): void {
  useEffect(() => {
    if (!active) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      onEscape();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [active, onEscape]);
}
