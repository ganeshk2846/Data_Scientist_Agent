/**
 * The keyboard, declared once.
 *
 * This registry is the single source of truth for what a key does, so the
 * shortcuts sheet cannot drift out of step with the handlers — the sheet is
 * rendered *from* this list, not written alongside it.
 *
 * Single-letter shortcuts are inert while typing and inert with any modifier
 * held, so they never fight the browser's own bindings.
 */

export interface Shortcut {
  /** The caps to draw, in order. */
  keys: readonly string[];
  label: string;
  group: 'Asking' | 'Moving' | 'The answer' | 'The product';
}

export const SHORTCUTS: readonly Shortcut[] = [
  { keys: ['⌘', 'K'], label: 'Command palette — ask anything, jump anywhere', group: 'Asking' },
  { keys: ['Enter'], label: 'Ask the question', group: 'Asking' },
  { keys: ['⇧', 'Enter'], label: 'New line inside the question', group: 'Asking' },
  { keys: ['N'], label: 'New question', group: 'Asking' },

  { keys: ['J'], label: 'Next question in the history rail', group: 'Moving' },
  { keys: ['K'], label: 'Previous question in the history rail', group: 'Moving' },
  { keys: ['B'], label: 'Pinboard', group: 'Moving' },
  { keys: ['Esc'], label: 'Close any overlay', group: 'Moving' },

  { keys: ['S'], label: 'Star this answer', group: 'The answer' },
  { keys: ['⇧', 'P'], label: 'Pin the headline figure to the pinboard', group: 'The answer' },
  { keys: ['C'], label: 'Copy the SQL', group: 'The answer' },
  { keys: ['I'], label: 'Run inspector — the pipeline, stage by stage', group: 'The answer' },
  { keys: ['P'], label: 'Presentation mode', group: 'The answer' },

  { keys: ['?'], label: 'This sheet', group: 'The product' },
];

export const SHORTCUT_GROUPS: readonly Shortcut['group'][] = [
  'Asking',
  'Moving',
  'The answer',
  'The product',
];
