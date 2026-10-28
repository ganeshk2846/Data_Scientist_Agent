import { useEffect } from 'react';

/** Ctrl/Cmd+K focuses the question box. Esc is handled where overlays live. */
export function useAskHotkey(onFocusAsk: () => void): void {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== 'k') return;
      if (!event.metaKey && !event.ctrlKey) return;
      event.preventDefault();
      onFocusAsk();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onFocusAsk]);
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
