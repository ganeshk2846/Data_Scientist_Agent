import { useCallback, useEffect, useRef } from 'react';

/**
 * Writes the pointer position onto an element as `--mx` / `--my`, which the
 * `.sheen` utility reads. Updates are coalesced into one animation frame, so a
 * fast pointer cannot cause a layout thrash.
 *
 * Returns a ref to attach to the surface. Disabled under reduced motion, and a
 * no-op on touch, where there is no hover to speak of.
 */
export function useSheen<T extends HTMLElement>(enabled = true) {
  const ref = useRef<T | null>(null);
  const frame = useRef(0);
  const next = useRef<{ x: number; y: number } | null>(null);

  const onPointerMove = useCallback(
    (event: PointerEvent) => {
      if (!enabled || event.pointerType === 'touch') return;
      const node = ref.current;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      next.current = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      if (frame.current) return;
      frame.current = window.requestAnimationFrame(() => {
        frame.current = 0;
        const point = next.current;
        if (!point || !ref.current) return;
        ref.current.style.setProperty('--mx', `${point.x}px`);
        ref.current.style.setProperty('--my', `${point.y}px`);
      });
    },
    [enabled],
  );

  useEffect(() => {
    const node = ref.current;
    if (!node || !enabled) return;
    node.addEventListener('pointermove', onPointerMove);
    return () => {
      node.removeEventListener('pointermove', onPointerMove);
      if (frame.current) window.cancelAnimationFrame(frame.current);
    };
  }, [enabled, onPointerMove]);

  return ref;
}
