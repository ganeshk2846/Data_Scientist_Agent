/**
 * Live end-to-end verification against the real backend.
 *
 * Asks each of the four verified suggestion chips, waits for the briefing to
 * settle, and asserts that the run actually reached `answered` with a
 * conclusion, evidence, SQL and claims on the page — plus that the pipeline
 * stages lit up and nothing was logged to the console.
 *
 * This is a gate, not a design review: every check is a DOM fact, so a pass
 * means the feature works rather than that it looked right.
 *
 *   node scripts/verify-live.mjs
 */

import { chromium } from 'playwright';

const BASE = process.env.BASE_URL ?? 'http://localhost:5173';

/** The four chips, verified in CLAUDE.md to return a full answered briefing. */
const CHIPS = [
  'How many orders were there in August 2018?',
  'Why did revenue spike in November 2017?',
  'How did revenue in 2018 compare to 2017?',
  'Was order count unusual in August 2018?',
];

const results = [];
const record = (name, pass, note = '') => {
  results.push({ name, pass, note });
  process.stdout.write(`${pass ? 'PASS' : 'FAIL'}  ${name}${note ? `  — ${note}` : ''}\n`);
};

/** A live governed run can take the better part of a minute. */
const RUN_TIMEOUT = 90_000;

async function settle(page) {
  // The briefing is settled when the Verified seal is on the page, or when a
  // designed non-answered state is. Either ends the wait; the caller decides
  // whether that was the right outcome.
  await page.waitForFunction(
    () =>
      !!document.querySelector('section[aria-label="Verification"]') ||
      !!document.querySelector('[data-state-shell]') ||
      /Needs clarifying|Refused|Blocked|Error|Insufficient/.test(
        document.body.innerText,
      ),
    undefined,
    { timeout: RUN_TIMEOUT },
  );
  await page.waitForTimeout(1_200);
}

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  await context.addInitScript(() => {
    try {
      window.localStorage.setItem('ds-agent-tour-seen', 'seen');
    } catch {
      /* private mode */
    }
  });

  const page = await context.newPage();
  const consoleErrors = [];
  const probeNoise = [];
  // Every /api/runs/__probe__ request is the backend-liveness probe, and its
  // 404 is the success case. Chromium logs it as a console error regardless,
  // so those lines are tracked apart from genuine errors.
  let probeRequests = 0;
  page.on('response', (r) => {
    if (r.url().includes('/api/runs/__probe__')) probeRequests += 1;
  });
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const text = m.text();
    if (/status of 404/.test(text) && probeRequests > 0) probeNoise.push(text);
    else consoleErrors.push(text);
  });
  page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`));

  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });

  // The backend must actually be reachable, or every check below is vacuous.
  const live = await page
    .locator('header')
    .getByText('Live', { exact: true })
    .count();
  record('backend reachable (top bar reads Live)', live > 0);

  for (const chip of CHIPS) {
    const label = `chip: ${chip.slice(0, 44)}…`;
    try {
      // Always start from the hero, so each chip is an independent run.
      await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
      await page.getByRole('button', { name: chip }).click();

      // The pipeline has to visibly run, not just the answer appear.
      const ranStages = await page
        .waitForFunction(
          () => {
            const track = document.querySelector('[aria-label="Pipeline stages"]');
            if (!track) return false;
            return track.textContent?.includes('running') || /\d+\/\d+/.test(
              document.body.innerText,
            );
          },
          undefined,
          { timeout: 30_000 },
        )
        .then(() => true)
        .catch(() => false);

      await settle(page);

      const facts = await page.evaluate(() => {
        const text = document.body.innerText;
        // `SectionLabel` uppercases through CSS, so innerText is uppercased.
        const has = (needle) => text.toLowerCase().includes(needle.toLowerCase());
        const seal = document.querySelector('section[aria-label="Verification"]');
        // The conclusion is the serif narrative in the lead card; a claim mark
        // is a <sup>-bearing button inside it.
        const conclusion = document.querySelector('article p.font-serif');
        return {
          answered: has('Answered'),
          hasSeal: !!seal,
          sealText: seal?.textContent?.replace(/\s+/g, ' ').trim().slice(0, 80) ?? '',
          hasConclusion: !!conclusion && (conclusion.textContent?.length ?? 0) > 40,
          hasSqlSection: has('How this was computed'),
          sqlLines: document.querySelectorAll('pre code span.contents').length,
          hasEvidence: has('Evidence'),
          evidenceCards: document.querySelectorAll(
            'section[data-tour="lineage"] > div > div',
          ).length,
          // Claim ids are rendered as monospace C-numbers in the ledger chips.
          claimIds: [
            ...new Set(
              [...document.querySelectorAll('.font-mono')]
                .map((n) => n.textContent?.trim() ?? '')
                .filter((t) => /^C\d+$/.test(t)),
            ),
          ],
          stageTicks: document.querySelectorAll(
            '[aria-label="Pipeline stages"] [role="listitem"]',
          ).length,
          pipelineSummary: /Pipeline · \d+ stages/.test(text),
        };
      });

      const problems = [];
      if (!facts.answered) problems.push('status is not Answered');
      if (!facts.hasConclusion) problems.push('no conclusion narrative');
      if (!facts.hasSqlSection || facts.sqlLines === 0) problems.push('no SQL');
      if (!facts.hasEvidence) problems.push('no evidence section');
      if (facts.claimIds.length === 0) problems.push('no claim ids');
      if (!facts.hasSeal) problems.push('no Verified seal');

      record(
        label,
        problems.length === 0,
        problems.length
          ? problems.join('; ')
          : `claims ${facts.claimIds.join(',')} · sql lines ${facts.sqlLines} · ${facts.sealText}`,
      );
      record(`  ↳ pipeline ran for that chip`, ranStages || facts.pipelineSummary);
    } catch (error) {
      record(label, false, error.message.split('\n')[0]);
    }
  }

  record(
    'no console errors during live runs',
    consoleErrors.length === 0,
    consoleErrors.length
      ? consoleErrors.slice(0, 4).join(' | ')
      : `${probeNoise.length} expected 404(s) from the liveness probe, excluded`,
  );

  await browser.close();

  const failed = results.filter((r) => !r.pass);
  process.stdout.write(
    `\n${results.length - failed.length}/${results.length} passed\n`,
  );
  if (failed.length) process.exitCode = 1;
}

await main();
