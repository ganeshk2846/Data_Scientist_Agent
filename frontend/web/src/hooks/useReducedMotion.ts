import { useEffect, useState } from 'react';

/**
 * True when motion should be skipped — because the OS asked for it, or because
 * the reader set the Atelier's motion dial to Reduced.
 *
 * `index.css` already neutralises CSS transitions for both cases. This hook is
 * for Framer Motion, which animates outside CSS and has to be told to skip, and
 * for the handful of components that choose a different *composition* rather
 * than just a shorter one (the hero grid freezes, `CountUp` prints its final
 * value, the listening waveform draws flat).
 *
 * The Atelier's setting is read off `<html data-motion>` with a MutationObserver
 * rather than passed in as a prop, so a component deep in the tree does not
 * need the settings controller threaded down to it.
 */
function read(): boolean {
  if (typeof window === 'undefined') return false;
  if (document.documentElement.getAttribute('data-motion') === 'reduced') return true;
  if (!window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(read);

  useEffect(() => {
    const update = () => setReduced(read());

    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    query?.addEventListener('change', update);

    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-motion'],
    });

    // The attribute may have been stamped between the first read and here.
    update();

    return () => {
      query?.removeEventListener('change', update);
      observer.disconnect();
    };
  }, []);

  return reduced;
}
