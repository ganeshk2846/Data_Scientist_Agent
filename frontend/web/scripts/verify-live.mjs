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
 * Each chip gets its **own browser context**, and the run id on the page is
 * checked against the ones already seen. Both matter: the app persists the
 * last briefings to `localStorage` (`ds-agent-history`), so a reused context
 * restores the previous answer — complete with its Verified seal — the instant
 * the page loads, and a wait for "the seal is present" would return against
 * the *old* run. A fresh context starts with no stored history, and the run id
 * proves the briefing being asserted is the one this chip just produced.
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

/**
 * The run id the top bar prints — `shortRunId(runId)`, so eight hex characters
 * of a uuid4 hex followed by an ellipsis. Null until a run is in flight.
 *
 * The pattern is anchored on the whole trimmed node for a reason: the footer
 * rail also carries a bare twelve-hex catalog digest, and a looser match would
 * read that instead and never change between chips.
 */
const RUN_ID = /^[0-9a-f]{8}…$/;

const runIdOnPage = (page) =>
  page.evaluate(
    (pattern) =>
      [...document.querySelectorAll('.font-mono')]
        .map((node) => (node.textContent ?? '').trim())
        .find((text) => new RegExp(pattern).test(text)) ?? null,
    RUN_ID.source,
  );

/**
 * Waits for a run that is *not* one of `seen` to finish.
 *
 * The settle signal is the Verified seal or a designed non-answered state —
 * but only once the run id on the page is new, so a briefing restored from
 * storage can never end the wait. The caller decides whether the outcome was
 * the right one.
 */
async function settle(page, seen) {
  await page.waitForFunction(
    ({ known, pattern }) => {
      const ids = [...document.querySelectorAll('.font-mono')]
        .map((n) => (n.textContent ?? '').trim())
        .filter((t) => new RegExp(pattern).test(t));
      const fresh = ids.some((id) => !known.includes(id));
      const settled =
        !!document.querySelector('section[aria-label="Verification"]') ||
        !!document.querySelector('[data-state-shell]') ||
        /Needs clarifying|Refused|Blocked|Error|Insufficient/.test(
          document.body.innerText,
        );
      // `ids.length === 0` keeps the wait honest if the top bar's run id is
      // ever hidden at this width: the terminal signal still ends it, and the
      // fresh context is what guarantees the briefing is this run's.
      return settled && (fresh || ids.length === 0);
    },
    { known: [...seen], pattern: RUN_ID.source },
    { timeout: RUN_TIMEOUT },
  );
  await page.waitForTimeout(1_200);
}

async function main() {
  const browser = await chromium.launch();

  const consoleErrors = [];
  const probeNoise = [];

  /**
   * A fresh context, and therefore a fresh `localStorage`, per chip.
   *
   * Clearing storage is what makes the run-id check below meaningful: with no
   * `ds-agent-history` entry there is no previous briefing to restore, so the
   * only envelope that can appear is the one this chip produces.
   */
  async function freshPage() {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
    });
    await context.addInitScript(() => {
      try {
        window.localStorage.clear();
        window.sessionStorage.clear();
        window.localStorage.setItem('ds-agent-tour-seen', 'seen');
      } catch {
        /* private mode */
      }
    });
    const page = await context.newPage();
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
    return { context, page };
  }

  {
    const { context, page } = await freshPage();
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });

    // The backend must actually be reachable, or every check below is vacuous.
    const live = await page
      .locator('header')
      .getByText('Live', { exact: true })
      .count();
    record('backend reachable (top bar reads Live)', live > 0);
    await context.close();
  }

  /** Every run id already asserted, so a repeat can never pass for a new run. */
  const seenRunIds = new Set();

  for (const chip of CHIPS) {
    const label = `chip: ${chip.slice(0, 44)}…`;
    const { context, page } = await freshPage();
    try {
      await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
      // A clean context must start with no briefing at all. If this ever
      // fails, storage leaked and nothing below can be trusted.
      const stale = await runIdOnPage(page);
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

      await settle(page, seenRunIds);
      const runId = await runIdOnPage(page);

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
      if (stale) problems.push(`storage leaked a previous briefing (${stale})`);
      if (!runId) problems.push('no run id on the page');
      else if (seenRunIds.has(runId)) problems.push(`re-read run ${runId}`);
      if (runId) seenRunIds.add(runId);
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
          : `run ${runId} · claims ${facts.claimIds.join(',')} · sql lines ${
              facts.sqlLines
            } · ${facts.sealText}`,
      );
      record(`  ↳ pipeline ran for that chip`, ranStages || facts.pipelineSummary);
    } catch (error) {
      record(label, false, error.message.split('\n')[0]);
      record(`  ↳ pipeline ran for that chip`, false, 'the run did not complete');
    } finally {
      await context.close();
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
