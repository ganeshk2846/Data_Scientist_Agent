import { useMemo } from 'react';

/**
 * A hand-rolled SQL highlighter.
 *
 * No library: every popular one ships a theme built on purples and pinks, and
 * overriding them is more work than tokenising SQL. Four token classes, all in
 * palette — gold for keywords, sage for strings, warm grey for comments.
 */

const KEYWORDS = new Set([
  'select', 'from', 'where', 'and', 'or', 'not', 'in', 'is', 'null', 'as', 'on',
  'join', 'inner', 'left', 'right', 'full', 'outer', 'cross', 'group', 'by',
  'order', 'having', 'limit', 'offset', 'with', 'union', 'all', 'distinct',
  'case', 'when', 'then', 'else', 'end', 'count', 'sum', 'avg', 'min', 'max',
  'cast', 'coalesce', 'between', 'like', 'asc', 'desc', 'over', 'partition',
  'round', 'abs', 'date', 'strftime', 'substr', 'exists', 'using', 'inner',
]);

type TokenKind = 'keyword' | 'string' | 'number' | 'comment' | 'plain';

interface Token {
  kind: TokenKind;
  text: string;
}

const CLASS: Record<TokenKind, string> = {
  keyword: 'text-gold',
  string: 'text-sage',
  number: 'text-ink',
  comment: 'text-ink-faint italic',
  plain: 'text-ink-muted',
};

function tokenise(sql: string): readonly Token[] {
  const tokens: Token[] = [];
  // One pass: comments, then quoted runs, then words and numbers.
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
      tokens.push({
        kind: KEYWORDS.has(word.toLowerCase()) ? 'keyword' : 'plain',
        text,
      });
    }
    last = match.index + text.length;
  }
  if (last < sql.length) tokens.push({ kind: 'plain', text: sql.slice(last) });
  return tokens;
}

export function SqlBlock({ sql }: { sql: string }) {
  const tokens = useMemo(() => tokenise(sql), [sql]);

  return (
    <pre className="overflow-x-auto rounded-sm border border-hairline bg-sunken p-4 font-mono text-[0.8125rem] leading-[1.6875rem]">
      <code>
        {tokens.map((token, index) => (
          <span key={index} className={CLASS[token.kind]}>
            {token.text}
          </span>
        ))}
      </code>
    </pre>
  );
}
