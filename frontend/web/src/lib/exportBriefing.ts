/**
 * "Copy as briefing" — the envelope as clean Markdown.
 *
 * Every line is transcribed from the envelope. Nothing is summarised,
 * recalculated or inferred: if a field is absent, its section is omitted rather
 * than filled in.
 */

import { formatDuration, formatNumber, formatWindow, humanise } from './format';
import { CLAIM_KIND_LABEL } from './claims';
import { asAnomalyResult, asDriverResult, asLookup, sortDrivers } from './evidence';
import type { AnswerEnvelope } from '@/types/envelope';

function heading(envelope: AnswerEnvelope, question: string | null): string[] {
  const lines = [`# ${question ?? 'Briefing'}`, ''];
  const facts = [
    `**Status** ${humanise(envelope.status)}`,
    `**Route** ${envelope.route.labels.join(', ')}`,
    `**Confidence** ${Math.round(envelope.route.confidence * 100)}%`,
  ];
  if (envelope.scope?.metric) facts.push(`**Metric** ${humanise(envelope.scope.metric)}`);
  const window = formatWindow(envelope.scope?.window ?? null);
  if (window) facts.push(`**Period** ${window}`);
  if (envelope.scope?.governed) facts.push('**Governed** yes');
  lines.push(facts.join(' · '), '');
  return lines;
}

export function briefingToMarkdown(
  envelope: AnswerEnvelope,
  question: string | null,
): string {
  const lines: string[] = heading(envelope, question);

  if (envelope.conclusion) {
    lines.push('## Conclusion', '', envelope.conclusion, '');
  }

  if (envelope.clarification) {
    lines.push(
      '## Clarification needed',
      '',
      `**Understood** ${envelope.clarification.what_understood}`,
      '',
      `**Needs clarifying** ${envelope.clarification.what_needs_clarification}`,
      '',
    );
  }

  if (envelope.refusal) {
    lines.push('## Refused', '');
    for (const item of envelope.refusal.missing) lines.push(`- ${item}`);
    if (envelope.refusal.closest_answerable) {
      lines.push('', `**Closest answerable** ${envelope.refusal.closest_answerable}`);
    }
    lines.push('');
  }

  if (envelope.block) {
    lines.push(
      '## Blocked',
      '',
      `**Reason** ${humanise(envelope.block.reason)}`,
      '',
      envelope.block.detail,
      '',
    );
  }

  if ((envelope.claims?.length ?? 0) > 0) {
    lines.push('## Claims', '');
    for (const claim of (envelope.claims ?? [])) {
      const numbers = claim.numbers.map((number) => number.token).join(', ');
      lines.push(
        `- **${claim.claim_id}** ${claim.text}  ` +
          `\n  _${CLAIM_KIND_LABEL[claim.kind]} · grade ${claim.grade} · ` +
          `source ${claim.source.type} ${claim.source.id}_` +
          (numbers ? `\n  Numbers: \`${numbers}\`` : ''),
      );
    }
    lines.push('');
  }

  // Evidence, each block in its own voice.
  const evidenceLines: string[] = [];
  for (const block of (envelope.evidence ?? [])) {
    const anomaly = asAnomalyResult(block);
    if (anomaly) {
      evidenceLines.push(
        `### Anomaly — ${anomaly.window}`,
        '',
        `- Verdict: **${humanise(anomaly.verdict)}**`,
        `- Actual: ${formatNumber(anomaly.actual)}`,
        `- Expected: ${formatNumber(anomaly.expected)} ` +
          `(range ${formatNumber(anomaly.expected_range[0])}–${formatNumber(anomaly.expected_range[1])})`,
        `- Deviation: ${anomaly.deviation_pct.toFixed(2)}%`,
        `- Baseline: ${humanise(anomaly.baseline_kind)} · persistence ${humanise(anomaly.persistence)}`,
        '',
      );
      continue;
    }

    const driver = asDriverResult(block);
    if (driver) {
      evidenceLines.push(
        `### Drivers — ${driver.metric}, ${driver.current_period} vs ${driver.comparison_period}`,
        '',
        `Total change: ${formatNumber(driver.total_change)}`,
        '',
        '| Dimension | Value | Contribution | Share | Interval | n | Grade |',
        '| --- | --- | --- | --- | --- | --- | --- |',
      );
      for (const item of sortDrivers(driver)) {
        evidenceLines.push(
          `| ${item.dimension} | ${item.value} | ${formatNumber(item.contribution)} | ` +
            `${(item.share * 100).toFixed(1)}% | ` +
            `${formatNumber(item.interval[0])} to ${formatNumber(item.interval[1])} | ` +
            `${formatNumber(item.sample_size)} | ${item.grade}${item.unstable ? ' (unstable)' : ''} |`,
        );
      }
      evidenceLines.push('');
      continue;
    }

    const lookup = asLookup(block);
    if (lookup) {
      evidenceLines.push(`### Result — ${lookup.query_id}`, '');
      const header = lookup.columns.map((column) => column.name);
      evidenceLines.push(
        `| ${header.join(' | ')} |`,
        `| ${header.map(() => '---').join(' | ')} |`,
      );
      for (const row of lookup.rows.slice(0, 25)) {
        evidenceLines.push(
          `| ${row
            .map((cell) => (typeof cell === 'number' ? formatNumber(cell) : String(cell ?? '—')))
            .join(' | ')} |`,
        );
      }
      if (lookup.rows.length > 25) {
        evidenceLines.push('', `_${lookup.rows.length - 25} further rows not shown._`);
      }
      evidenceLines.push('');
    }
  }
  if (evidenceLines.length > 0) lines.push('## Evidence', '', ...evidenceLines);

  if ((envelope.queries?.length ?? 0) > 0) {
    lines.push('## How this was computed', '');
    for (const query of (envelope.queries ?? [])) {
      const meta = [
        query.status,
        formatDuration(query.duration_ms),
        query.origin,
        ...(query.rows_scanned != null
          ? [`${formatNumber(query.rows_scanned)} rows scanned`]
          : []),
        ...(query.validation_mode ? [query.validation_mode] : []),
      ].join(' · ');
      lines.push(`**${query.query_id}** — ${meta}`, '', '```sql', query.sql, '```', '');
    }
  }

  if ((envelope.caveats?.length ?? 0) > 0) {
    lines.push('## Caveats', '');
    for (const caveat of (envelope.caveats ?? [])) lines.push(`- ${caveat}`);
    lines.push('');
  }

  if (envelope.causal_boundary_note) {
    lines.push('## Causal boundary', '', envelope.causal_boundary_note, '');
  }

  if (envelope.next_actions.length > 0) {
    lines.push('## Next actions', '');
    for (const action of [...envelope.next_actions].sort((a, b) => a.rank - b.rank)) {
      lines.push(`### ${action.rank}. ${action.title}`, '');
      const block = (title: string, items: readonly string[]) => {
        if (items.length === 0) return;
        lines.push(`**${title}**`, '');
        for (const item of items) lines.push(`- ${item}`);
        lines.push('');
      };
      block('Assumptions', action.assumptions);
      block('Trade-offs', action.trade_offs);
      block('Monitor', action.monitor);
      block('Would change the ranking', action.data_that_would_change_ranking);
      if (action.sensitivity) lines.push(`**Sensitivity** ${action.sensitivity}`, '');
    }
  }

  const metrics = envelope.run_metrics;
  lines.push(
    '---',
    '',
    `Latency ${formatDuration(metrics.latency_ms)} · ` +
      `${formatNumber(metrics.queries)} queries · ` +
      `${formatNumber(metrics.rows)} rows · ` +
      `${formatNumber(metrics.tokens)} tokens` +
      (metrics.retries > 0 ? ` · ${formatNumber(metrics.retries)} retries` : ''),
    '',
    `Run \`${envelope.run_id}\` · contract ${envelope.contract_version}` +
      (envelope.provenance.catalog_version
        ? ` · catalog ${envelope.provenance.catalog_version}`
        : '') +
      ` · snapshot ${envelope.provenance.snapshot_id || 'unknown'}` +
      ` · ${envelope.provenance.timestamp}`,
    '',
    '_Generated by DS-AGENT-CORE. Every figure above is transcribed from the' +
      ' run’s answer envelope; the interface computes nothing._',
  );

  return lines.join('\n');
}
