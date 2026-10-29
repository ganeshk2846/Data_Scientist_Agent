import { useEffect } from 'react';

import { STATUS_LABEL } from '@/components/briefing/StatusBadge';
import type { RunPhase } from '@/lib/runState';
import type { RunStatus } from '@/types/envelope';

/**
 * The tab itself reports the run.
 *
 * A governed query can take the better part of a minute, and the reader will
 * have switched tabs. So the title says where the run is, and the favicon is
 * drawn — not loaded — as a small instrument mark whose state matches: a hollow
 * ring while it works, a filled mark when it answers, a hairline bar when it
 * needs something, a cut mark when it failed.
 *
 * It is generated from the live accent token, so it re-draws when the Atelier
 * changes accent and the tab matches the product.
 */

type Mark = 'idle' | 'running' | 'ok' | 'attention' | 'fault';

function markFor(phase: RunPhase, status: RunStatus | null): Mark {
  if (phase === 'submitting' || phase === 'streaming' || phase === 'fetching') {
    return 'running';
  }
  if (phase === 'failed') return 'fault';
  switch (status) {
    case 'answered':
      return 'ok';
    case 'clarify':
    case 'refused':
    case 'insufficient_evidence':
      return 'attention';
    case 'blocked':
    case 'error':
      return 'fault';
    default:
      return 'idle';
  }
}

const BASE_TITLE = 'Data Scientist';

function titleFor(phase: RunPhase, status: RunStatus | null, question: string | null): string {
  if (phase === 'submitting' || phase === 'streaming') return `Running — ${BASE_TITLE}`;
  if (phase === 'fetching') return `Collecting — ${BASE_TITLE}`;
  if (phase === 'failed') return `Failed — ${BASE_TITLE}`;
  if (!status || !question) return `${BASE_TITLE} · Decision Intelligence`;
  const short = question.length > 48 ? `${question.slice(0, 47)}…` : question;
  return `${STATUS_LABEL[status]} · ${short}`;
}

/** Reads a token off the document as a CSS colour. */
function token(name: string, fallback: string): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const parts = raw.split(/\s+/);
  return parts.length === 3 ? `rgb(${parts.join(',')})` : fallback;
}

function faviconFor(mark: Mark): string {
  const accent = token('--c-accent', 'rgb(184,151,90)');
  const ink = token('--c-ink-faint', 'rgb(103,98,90)');
  const bad = token('--c-terracotta', 'rgb(168,92,69)');

  // One 32×32 glyph, four states. Drawn, so it inherits the live accent.
  const body = {
    idle: `<circle cx="16" cy="16" r="9" fill="none" stroke="${ink}" stroke-width="2"/>`,
    running: `<circle cx="16" cy="16" r="9" fill="none" stroke="${accent}" stroke-width="2" stroke-dasharray="14 42" stroke-linecap="round" transform="rotate(-90 16 16)"/>`,
    ok: `<circle cx="16" cy="16" r="9" fill="${accent}"/>`,
    attention: `<circle cx="16" cy="16" r="9" fill="none" stroke="${accent}" stroke-width="2"/><rect x="15" y="10" width="2" height="8" fill="${accent}"/><rect x="15" y="20" width="2" height="2" fill="${accent}"/>`,
    fault: `<circle cx="16" cy="16" r="9" fill="none" stroke="${bad}" stroke-width="2"/><path d="M12 12 L20 20 M20 12 L12 20" stroke="${bad}" stroke-width="2" stroke-linecap="round"/>`,
  }[mark];

  return `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">${body}</svg>`,
  )}`;
}

export function useDocumentStatus(
  phase: RunPhase,
  status: RunStatus | null,
  question: string | null,
  /** Included so a change of accent re-draws the mark. */
  accent: string,
): void {
  useEffect(() => {
    document.title = titleFor(phase, status, question);

    const href = faviconFor(markFor(phase, status));
    let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) {
      link = document.createElement('link');
      link.rel = 'icon';
      document.head.appendChild(link);
    }
    link.type = 'image/svg+xml';
    link.href = href;
  }, [accent, phase, question, status]);
}
