import { useMemo } from 'react';

import { cx } from '@/lib/cx';

/**
 * A hand-rolled SQL highlighter with a line-number gutter.
 *
 * No library: every popular one ships a theme built on purples and pinks, and
 * overriding them is more work than tokenising SQL. Six token classes, all in
 * palette, and NONE of them the accent: a query is a field of a hundred
 * keywords, and an accent spread over a hundred things is not an accent. The
 * separation is carried by weight and tone — keywords in full ink at medium,
 * functions and identifiers in muted grey, strings in sage, comments faint and
 * italic.
 */

const KEYWORDS = new Set([
  'select', 'from', 'where', 'and', 'or', 'not', 'in', 'is', 'null', 'as', 'on',
  'join', 'inner', 'left', 'right', 'full', 'outer', 'cross', 'group', 'by',
  'order', 'having', 'limit', 'offset', 'with', 'union', 'all', 'distinct',
  'case', 'when', 'then', 'else', 'end', 'between', 'like', 'asc', 'desc',
  'over', 'partition', 'exists', 'using',
]);

// Functions read differently from clause keywords, so they get their own tone.
const FUNCTIONS = new Set([
  'count', 'sum', 'avg', 'min', 'max', 'cast', 'coalesce', 'round', 'abs',
  'date', 'strftime', 'substr', 'length', 'lower', 'upper', 'nullif',
]);

type TokenKind = 'keyword' | 'function' | 'string' | 'number' | 'comment' | 'plain';

interface Token {
  kind: TokenKind;
  text: string;
}

const CLASS: Record<TokenKind, string> = {
  keyword: 'font-medium text-ink',
  function: 'text-ink-muted',
  string: 'text-sage-ink',
  number: 'text-ink',
  comment: 'italic text-ink-faint',
  plain: 'text-ink-muted',
};

function tokenise(sql: string): readonly Token[] {
  const tokens: Token[] = [];
  const pattern =
    /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^']|'')*'|"(?:[^"]|"")*")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)/g;
  let last = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(sql)) !== null) {
    if (match.index > last) {
      tokens.push({ kind: 'plain', text: sql.slice(last, match.index) });
    }
    const [text, comment, quoted, numeric, word] = match;
    if (comment) tokens.push({ kind: 'comment', text });
    else if (quoted) tokens.push({ kind: 'string', text });
    else if (numeric) tokens.push({ kind: 'number', text });
    else if (word) {
      const lower = word.toLowerCase();
      tokens.push({
        kind: KEYWORDS.has(lower) ? 'keyword' : FUNCTIONS.has(lower) ? 'function' : 'plain',
        text,
      });
    }
    last = match.index + text.length;
  }
  if (last < sql.length) tokens.push({ kind: 'plain', text: sql.slice(last) });
  return tokens;
}

/** Tokens are split per line, so the gutter can align to real rows. */
function tokeniseLines(sql: string): readonly (readonly Token[])[] {
  const lines: Token[][] = [[]];
  for (const token of tokenise(sql)) {
    const parts = token.text.split('\n');
    parts.forEach((part, index) => {
      if (index > 0) lines.push([]);
      if (part) lines[lines.length - 1]?.push({ kind: token.kind, text: part });
    });
  }
  return lines;
}

export function SqlBlock({
  sql,
  className,
  /** Names the scroll region. A long query scrolls sideways on a narrow
      screen, and a region with its own scrollbar must be focusable or a
      keyboard user cannot reach the rest of the line. */
  label = 'SQL',
}: {
  sql: string;
  className?: string;
  label?: string;
}) {
  const lines = useMemo(() => tokeniseLines(sql), [sql]);

  return (
    <div
      data-print="flow"
      tabIndex={0}
      role="region"
      aria-label={label}
      className={cx(
        'overflow-x-auto rounded-sm border border-hairline bg-sunken',
        className,
      )}
    >
      <pre className="min-w-full py-3 font-mono text-[0.8125rem] leading-[1.6875rem]">
        <code className="grid" style={{ gridTemplateColumns: 'auto 1fr' }}>
          {lines.map((tokens, index) => (
            <span key={index} className="contents">
              {/* Gutter: select-none so copying the block never drags numbers in. */}
              <span
                aria-hidden
                className="select-none border-r border-hairline px-3 text-right text-[0.6875rem] tabular-nums text-ink-faint"
              >
                {index + 1}
              </span>
              <span className="whitespace-pre px-4">
                {tokens.length === 0 ? ' ' : null}
                {tokens.map((token, position) => (
                  <span key={position} className={CLASS[token.kind]}>
                    {token.text}
                  </span>
                ))}
              </span>
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}
