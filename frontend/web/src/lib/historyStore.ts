/**
 * The question history, persisted locally.
 *
 * The rail used to be in-memory on the reasoning that the backend's run store
 * is process-local, so a reload could not reopen a run anyway. That is still
 * true of the *backend* — but the envelope itself is a complete, self-contained
 * document, so once we have it we can reopen the briefing from our own copy
 * without the service at all. Everything here is therefore a local cache, and
 * every surface that reads it says "stored in this browser".
 *
 * Stored envelopes come from an older build of this app, which makes them as
 * untrustworthy as anything off the wire. `validateEnvelope` checks every field
 * the briefing dereferences without guarding; an entry that fails keeps its
 * question and drops its envelope rather than crashing a render.
 */

import { KEYS, isRecord, readJson, writeJson } from './storage';
import type { AnswerEnvelope, RunStatus } from '@/types/envelope';

export interface StoredEntry {
  localId: string;
  runId: string | null;
  question: string;
  askedAt: number;
  status: RunStatus | null;
  envelope: AnswerEnvelope | null;
  clarificationOf: string | null;
  starred: boolean;
  /**
   * The conversation (topic) this question belongs to. Entries stored before
   * threads existed have none and each reads as its own conversation.
   */
  threadId?: string;
}

const STATUSES: readonly string[] = [
  'answered',
  'clarify',
  'refused',
  'blocked',
  'insufficient_evidence',
  'error',
];

function isStatus(value: unknown): value is RunStatus {
  return typeof value === 'string' && STATUSES.includes(value);
}

/** Every key the briefing reads without a guard must be present and the right shape. */
function validateEnvelope(value: unknown): AnswerEnvelope | null {
  if (!isRecord(value)) return null;
  if (typeof value['run_id'] !== 'string') return null;
  if (typeof value['contract_version'] !== 'string') return null;
  if (!isStatus(value['status'])) return null;

  const route = value['route'];
  if (!isRecord(route) || !Array.isArray(route['labels'])) return null;
  if (typeof route['confidence'] !== 'number') return null;

  const scope = value['scope'];
  if (!isRecord(scope) || !Array.isArray(scope['filters'])) return null;

  for (const key of ['evidence', 'claims', 'method', 'queries', 'caveats', 'next_actions']) {
    if (!Array.isArray(value[key])) return null;
  }
  if (!isRecord(value['run_metrics']) || !isRecord(value['provenance'])) return null;

  return value as unknown as AnswerEnvelope;
}

function validateEntry(value: unknown): StoredEntry | null {
  if (!isRecord(value)) return null;
  const { localId, question } = value;
  if (typeof localId !== 'string' || typeof question !== 'string') return null;
  return {
    localId,
    runId: typeof value['runId'] === 'string' ? value['runId'] : null,
    question,
    askedAt: typeof value['askedAt'] === 'number' ? value['askedAt'] : Date.now(),
    status: isStatus(value['status']) ? value['status'] : null,
    envelope: validateEnvelope(value['envelope']),
    clarificationOf:
      typeof value['clarificationOf'] === 'string' ? value['clarificationOf'] : null,
    starred: value['starred'] === true,
    ...(typeof value['threadId'] === 'string' ? { threadId: value['threadId'] } : {}),
  };
}

/**
 * How many questions are kept. Envelopes carry their own SQL and result rows,
 * so a long history is a real amount of data; 40 is several sessions' worth and
 * stays comfortably inside a 5 MB origin quota.
 */
const MAX_ENTRIES = 40;

export function loadHistory(): readonly StoredEntry[] {
  const stored = readJson<readonly StoredEntry[]>(KEYS.history, (value) => {
    if (!Array.isArray(value)) return null;
    const entries: StoredEntry[] = [];
    for (const item of value) {
      const entry = validateEntry(item);
      if (entry) entries.push(entry);
    }
    return entries;
  });
  return stored ?? [];
}

/**
 * Writes the history back. A run still in flight has no envelope worth keeping
 * and would be unreopenable after a reload, so it is dropped on the way out.
 */
export function saveHistory(entries: readonly StoredEntry[]): void {
  writeJson(
    KEYS.history,
    entries.filter((entry) => entry.status !== null).slice(0, MAX_ENTRIES),
  );
}
