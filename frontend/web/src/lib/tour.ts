/**
 * The first-run tour: four steps, once, skippable, replayable from settings.
 *
 * Each step names an element by `data-tour` attribute rather than by a CSS
 * selector or a ref passed through the tree. The spotlight measures whatever it
 * finds; a step whose target is not on screen is skipped rather than pointed at
 * empty space, which is what keeps the tour honest when it runs on the hero
 * (where there is no pipeline and no lineage yet).
 */

import { KEYS, readRaw, writeRaw } from './storage';

export interface TourStep {
  /** The value of the `data-tour` attribute on the element to spotlight. */
  target: string;
  eyebrow: string;
  title: string;
  body: string;
}

export const TOUR_STEPS: readonly TourStep[] = [
  {
    target: 'ask',
    eyebrow: 'One',
    title: 'Ask in plain English',
    body: 'Name a metric and a period — "revenue in August 2018". The builder beneath assembles one for you if you would rather pick than type.',
  },
  {
    target: 'pipeline',
    eyebrow: 'Two',
    title: 'Watch it think',
    body: 'Seven stages, streamed live: the guard, the router, the SQL, the executor, the analysts, the ledger and the fact checker. Open the inspector for every duration.',
  },
  {
    target: 'lineage',
    eyebrow: 'Three',
    title: 'Every figure traces back',
    body: 'Numbers in the narrative carry their claim ids. Touch one and it lights its evidence card and the exact SQL that produced it.',
  },
  {
    target: 'pinboard',
    eyebrow: 'Four',
    title: 'Keep what matters',
    body: 'Pin a headline figure and it becomes a tile on your pinboard. Refresh re-asks the question live and the new value counts in.',
  },
];

export function hasSeenTour(): boolean {
  return readRaw(KEYS.tour) === 'seen';
}

export function markTourSeen(): void {
  writeRaw(KEYS.tour, 'seen');
}
