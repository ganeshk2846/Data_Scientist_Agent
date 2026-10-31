/**
 * Mock-mode state coverage, the feature smoke test, and axe.
 *
 * Runs entirely against `?mock=1`, so every designed status is reachable
 * without a backend and each check is deterministic. Every assertion is a DOM
 * fact — a pass means the feature did the thing, not that it looked right.
 *
 *   node scripts/verify-features.mjs
 *   node scripts/verify-features.mjs --group=features
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

const HERE = dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE_URL ?? 'http://localhost:5173';
const AXE = readFileSync(
  join(HERE, '..', 'node_modules', 'axe-core', 'axe.min.js'),
  'utf8',
);

const wanted = process.argv
  .find((a) => a.startsWith('--group='))
  ?.slice('--group='.length);

const results = [];
function record(name, pass, note = '') {
  results.push({ name, pass, note });
  process.stdout.write(
    `${pass ? 'PASS' : 'FAIL'}  ${name}${note ? `  — ${note}` : ''}\n`,
  );
}

const LOOKUP = 'How many orders were there in August 2018?';
const ANOMALY = 'Was order count unusual in August 2018?';

let browser;

/**
 * A fresh context per check. Shared state is what makes a suite like this lie
 * to you: one leftover pin or star and the next assertion passes for the wrong
 * reason.
 */
async function fresh({ width = 1440, height = 1000, tourSeen = true } = {}) {
  const context = await browser.newContext({
    viewport: { width, height },
    permissions: ['clipboard-read', 'clipboard-write'],
  });
  if (tourSeen) {
    await context.addInitScript(() => {
      try {
        window.localStorage.setItem('ds-agent-tour-seen', 'seen');
      } catch {
        /* private mode */
      }
    });
  }
  const page = await context.newPage();
  const errors = [];
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  return { context, page, errors };
}

/**
 * Asks in mock mode and waits for the run to actually settle.
 *
 * The settle signal is the pipeline summary bar, which only renders once the
 * run is out of flight AND the envelope has been collected. Matching on the
 * state headings instead does not work under `?mock=1`: the MockBar lists every
 * status as a chip, so "BLOCKED" and "REFUSED" are already on the page before
 * a question is even asked, and the wait returns immediately.
 */
async function ask(page, question) {
  await page.getByRole('textbox', { name: /Ask your data/ }).fill(question);
  await page.keyboard.press('Enter');
  await page.waitForFunction(
    () => /Pipeline · \d+ stages/i.test(document.body.innerText),
    undefined,
    { timeout: 30_000 },
  );
  // Let the staggered reveal land, so nothing is asserted mid-animation.
  await page.waitForTimeout(1_600);
  // Single-letter shortcuts are ignored while typing, by design. Blur the
  // composer so a keyboard assertion tests the binding and not that rule.
  await page.evaluate(() => {
    const active = document.activeElement;
    if (active instanceof HTMLElement) active.blur();
  });
}

/* ────────────────────────────── 5. mock states ────────────────────────── */

/** The nine scenarios in lib/mock/envelopes.ts, and the state each must show. */
const MOCK_STATES = [
  { chip: /ANSWERED\s*lookup/i, expect: /Answered/i, id: 'answered · lookup' },
  { chip: /ANSWERED\s*comparative/i, expect: /Answered/i, id: 'answered · comparative' },
  { chip: /ANSWERED\s*anomaly/i, expect: /Answered/i, id: 'answered · anomaly' },
  { chip: /ANSWERED\s*driver/i, expect: /Answered/i, id: 'answered · driver' },
  { chip: /NEEDS CLARIFYING/i, expect: /One detail short of an answer/i, id: 'clarify' },
  { chip: /REFUSED/i, expect: /cannot be answered from the governed data/i, id: 'refused' },
  { chip: /BLOCKED/i, expect: /ingress guard stopped this request/i, id: 'blocked' },
  {
    chip: /INSUFFICIENT EVIDENCE/i,
    expect: /Not enough evidence to stand behind an answer/i,
    id: 'insufficient_evidence',
  },
  { chip: /^ERROR$/i, expect: /The run did not complete/i, id: 'error' },
];

async function mockStates() {
  const { context, page, errors } = await fresh();
  await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });

  for (const state of MOCK_STATES) {
    try {
      // The MockBar lists every scenario; clicking one routes to that status.
      const chip = page.getByRole('button', { name: state.chip }).first();
      await chip.click();
      await page.waitForFunction(
        (pattern) => new RegExp(pattern, 'i').test(document.body.innerText),
        state.expect.source,
        { timeout: 30_000 },
      );
      record(`mock state: ${state.id}`, true);
    } catch (error) {
      record(`mock state: ${state.id}`, false, error.message.split('\n')[0]);
    }
  }

  record(
    'mock mode: no console errors across all nine states',
    errors.length === 0,
    errors.slice(0, 3).join(' | '),
  );
  await context.close();
}

/* ─────────────────────────── 6. feature smoke test ────────────────────── */

async function features() {
  /* ---- command palette ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await page.keyboard.press('Control+k');
    const open = await page
      .locator('[aria-label="Command palette"]')
      .waitFor({ timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    // It must also be able to ask: type and Enter runs the question.
    let asked = false;
    if (open) {
      await page.getByRole('textbox', { name: 'Command palette query' }).fill('Pinboard');
      await page.waitForTimeout(400);
      // Row 0 is always "Ask <free text>"; the Go-to row is the next one down.
      await page.keyboard.press('ArrowDown');
      await page.keyboard.press('Enter');
      asked = await page
        .getByText(/Nothing pinned yet/i)
        .waitFor({ timeout: 5_000 })
        .then(() => true)
        .catch(() => false);
    }
    record('command palette (Ctrl+K) opens and routes', open && asked);
    await context.close();
  }

  /* ---- presentation mode ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    await page.keyboard.press('p');
    const on = await page
      .locator('[aria-label="Presentation"]')
      .waitFor({ timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    await page.keyboard.press('Escape');
    const off = await page
      .locator('[aria-label="Presentation"]')
      .waitFor({ state: 'detached', timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    record('presentation mode (P) opens, Esc closes', on && off);
    await context.close();
  }

  /* ---- copy as briefing + toast ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    await page.getByRole('button', { name: /Copy briefing/ }).click();
    const toasted = await page
      .getByText(/Briefing copied as Markdown/i)
      .waitFor({ timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    const looksRight =
      clip.includes('## Conclusion') && clip.includes('```sql') && clip.includes('## Claims');
    record(
      'copy as briefing writes Markdown to the clipboard',
      looksRight,
      `${clip.length} chars`,
    );
    record('toasts appear on action', toasted);
    await context.close();
  }

  /* ---- download PDF (print) ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    // Headless Chromium cannot show a print preview, so the check is that the
    // control actually calls window.print() and that the print stylesheet has
    // something to act on.
    await page.evaluate(() => {
      window.__printed = 0;
      window.print = () => {
        window.__printed += 1;
      };
    });
    await page.getByRole('button', { name: /Download PDF/ }).click();
    const printed = await page.evaluate(() => window.__printed);
    const printRules = await page.evaluate(() => {
      // Emulating print media is what proves the stylesheet is wired up.
      const hidden = document.querySelectorAll('[data-print="hide"]').length;
      const flow = document.querySelectorAll('[data-print="flow"]').length;
      return { hidden, flow };
    });
    record(
      'download PDF invokes the print dialogue',
      printed === 1,
      `data-print hide=${printRules.hidden} flow=${printRules.flow}`,
    );

    // And the print stylesheet really does drop the chrome.
    await page.emulateMedia({ media: 'print' });
    const chromeHidden = await page.evaluate(() => {
      const el = document.querySelector('header[data-print="hide"]');
      return el ? getComputedStyle(el).display === 'none' : false;
    });
    await page.emulateMedia({ media: 'screen' });
    record('print stylesheet hides the chrome under @media print', chromeHidden);
    await context.close();
  }

  /* ---- follow-ups ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    const section = page
      .locator('section')
      .filter({ hasText: /Continue/i })
      .last();
    const buttons = section.locator('button');
    const count = await buttons.count();
    // Clicking one must actually ask it.
    let navigated = false;
    if (count > 0) {
      const text = (await buttons.first().innerText()).replace(/\s+/g, ' ');
      await buttons.first().click();
      await page.waitForTimeout(1_800);
      const h1 = (await page.locator('h1').first().innerText()).trim();
      navigated = h1.length > 0 && text.includes(h1.slice(0, 14));
    }
    record('follow-ups render and ask when clicked', count > 0 && navigated, `${count} offered`);
    await context.close();
  }

  /* ---- Verified seal ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    const seal = page.locator('section[aria-label="Verification"]');
    const visible = await seal.isVisible();
    const text = (await seal.innerText()).replace(/\s+/g, ' ');
    const hallmark = await seal.locator('svg polygon').count();
    const counted = /(\d) of (\d) checks/.exec(text);
    record(
      'Verified seal visible with the struck hallmark',
      visible && hallmark === 1 && !!counted,
      `visible=${visible} octagon=${hallmark} count="${counted?.[0] ?? 'none'}"`,
    );
    await context.close();
  }

  /* ---- lineage hover ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    // A claim mark is the button around a number in the narrative.
    const mark = page.locator('article p button').first();
    const before = await page.locator('.border-accent').count();
    await mark.hover();
    await page.waitForTimeout(600);
    const after = await page.locator('.border-accent').count();
    const popover = await page
      .locator('[role="dialog"]')
      .first()
      .isVisible()
      .catch(() => false);
    record(
      'lineage lights on hover (claim → evidence → query)',
      after > before && popover,
      `accent-bordered elements ${before} → ${after}`,
    );
    await context.close();
  }

  /* ---- SQL copy ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    await page.getByRole('button', { name: /Copy SQL/i }).first().click();
    const became = await page
      .getByRole('button', { name: /SQL copied/i })
      .first()
      .waitFor({ timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    record(
      'SQL copy button copies the query',
      became && /select/i.test(clip),
      `${clip.split('\n').length} lines`,
    );

    // And the C shortcut copies every query in the run.
    await page.keyboard.press('c');
    await page.waitForTimeout(500);
    const clip2 = await page.evaluate(() => navigator.clipboard.readText());
    record('C shortcut copies the run’s SQL', /^-- Q1/m.test(clip2));
    await context.close();
  }

  /* ---- light / dark toggle ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await page.getByRole('radio', { name: 'Dark' }).click();
    await page.waitForTimeout(400);
    const dark = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    const darkBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    await page.getByRole('radio', { name: 'Light' }).click();
    await page.waitForTimeout(400);
    const light = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    const lightBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    record(
      'light / dark toggle swaps the token block',
      dark === 'dark' && light === 'light' && darkBg !== lightBg,
      `${darkBg} → ${lightBg}`,
    );
    await context.close();
  }

  /* ---- mobile 390px ---- */
  {
    const { context, page } = await fresh({ width: 390, height: 844 });
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    const heroOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    await ask(page, ANOMALY);
    const answerOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    record(
      'mobile 390px: no horizontal page overflow',
      heroOverflow <= 1 && answerOverflow <= 1,
      `hero +${heroOverflow}px, answer +${answerOverflow}px`,
    );
    await context.close();
  }

  /* ---- builder ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: /Build a question/ }).click();
    await page.getByRole('radio', { name: 'GMV' }).click();
    await page.getByRole('radio', { name: 'Unusual?' }).click();
    const preview = await page.locator('p.font-serif').last().innerText();
    const matches = /^Was GMV unusual in /.test(preview.trim());
    await page
      .locator('div')
      .filter({ hasText: /^The question/ })
      .getByRole('button', { name: /^Ask$/ })
      .last()
      .click();
    await page.waitForTimeout(1_500);
    const asked = (await page.locator('h1').first().innerText()).includes('Was GMV unusual');
    record(
      'guided builder composes and asks a verified pattern',
      matches && asked,
      preview.trim(),
    );
    await context.close();
  }

  /* ---- voice button ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    const supported = await page.evaluate(
      () => 'SpeechRecognition' in window || 'webkitSpeechRecognition' in window,
    );
    const shown = await page.getByRole('button', { name: /Dictate the question/ }).count();
    // Correct behaviour is "shown iff the engine exists" — both ways pass.
    record(
      'voice button follows feature detection',
      supported ? shown > 0 : shown === 0,
      supported
        ? `engine present, mic rendered (${shown})`
        : 'no engine in this browser, mic correctly absent',
    );
    await context.close();
  }

  /* ---- table sort / search / CSV ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, ANOMALY);
    await page.getByRole('radio', { name: 'Table' }).first().click();
    await page.waitForTimeout(400);

    // Scope every selector to the main lookup table. This page carries two
    // `DataTable`s — the lookup's result rows and the anomaly chart's "view as
    // table" — and ChartFrame keeps both views mounted, so an unscoped
    // `tbody tr` reads the two row sets concatenated and no single column is
    // ever monotonic across the join. `data-testid` names the one we mean.
    const TABLE = '[data-testid="lookup-table"]';
    const table = page.locator(TABLE);

    // "Sorted" means the clicked column is monotonic afterwards. Asserting
    // that the first row *changed* is wrong: this series is already ascending
    // by period, and its smallest measure legitimately sits in the first row.
    const column = 1;
    const readColumn = () =>
      page.evaluate(
        ([selector, index]) =>
          [...document.querySelectorAll(`${selector} tbody tr`)].map((row) =>
            Number(
              (row.children[index]?.textContent ?? '').replace(/[^0-9.-]/g, ''),
            ),
          ),
        [TABLE, column],
      );

    await table.locator('thead th button').nth(column).click();
    await page.waitForTimeout(300);
    const ascAttr = await table.locator('thead th').nth(column).getAttribute('aria-sort');
    const asc = await readColumn();
    const isAsc = asc.every((v, i) => i === 0 || asc[i - 1] <= v);

    await table.locator('thead th button').nth(column).click();
    await page.waitForTimeout(300);
    const descAttr = await table.locator('thead th').nth(column).getAttribute('aria-sort');
    const desc = await readColumn();
    const isDesc = desc.every((v, i) => i === 0 || desc[i - 1] >= v);

    record(
      'result table sorts by column (both directions)',
      ascAttr === 'ascending' && isAsc && descAttr === 'descending' && isDesc,
      `asc ${asc.slice(0, 3).join(',')}… monotonic=${isAsc}; desc ${desc
        .slice(0, 3)
        .join(',')}… monotonic=${isDesc}`,
    );

    // A third click clears the sort and restores the backend's own row order.
    await table.locator('thead th button').nth(column).click();
    await page.waitForTimeout(300);
    const clearedAttr = await table
      .locator('thead th')
      .nth(column)
      .getAttribute('aria-sort');
    record('a third click returns to the backend row order', clearedAttr === 'none');

    const search = table.getByRole('searchbox', { name: /Search/ });
    const rowsBefore = await table.locator('tbody tr').count();
    await search.fill('2018-01');
    await page.waitForTimeout(400);
    const rowsAfter = await table.locator('tbody tr').count();
    record(
      'result table searches rows',
      rowsAfter < rowsBefore && rowsAfter > 0,
      `${rowsBefore} → ${rowsAfter} rows`,
    );
    await search.fill('');
    await page.waitForTimeout(300);

    const download = page.waitForEvent('download', { timeout: 10_000 });
    await table.getByRole('button', { name: /Export CSV/ }).click();
    let csvName = '';
    let csvBody = '';
    try {
      const file = await download;
      csvName = file.suggestedFilename();
      const stream = await file.createReadStream();
      csvBody = (await new Promise((resolve, reject) => {
        let data = '';
        stream.on('data', (c) => (data += c));
        stream.on('end', () => resolve(data));
        stream.on('error', reject);
      })).slice(0, 120);
    } catch (error) {
      csvName = `FAILED: ${error.message.split('\n')[0]}`;
    }
    record(
      'Export CSV downloads the rows',
      /\.csv$/.test(csvName) && csvBody.includes(','),
      `${csvName} · starts "${csvBody.split('\r\n')[0]}"`,
    );
    await context.close();
  }

  /* ---- chart PNG ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, ANOMALY);
    const download = page.waitForEvent('download', { timeout: 15_000 });
    await page.getByRole('button', { name: /Download PNG/ }).first().click();
    let name = '';
    try {
      name = (await download).suggestedFilename();
    } catch (error) {
      name = `FAILED: ${error.message.split('\n')[0]}`;
    }
    record('chart Download PNG produces a file', /\.png$/.test(name), name);
    await context.close();
  }

  /* ---- run inspector ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, ANOMALY);
    await page.keyboard.press('i');
    const open = await page
      .locator('[aria-label="Run inspector"]')
      .waitFor({ timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    const lanes = await page.locator('[aria-label="Run inspector"] ol > li').count();
    const json = await page
      .locator('[aria-label="Raw answer envelope JSON"] pre')
      .innerText()
      .catch(() => '');
    record(
      'run inspector: waterfall lanes + raw envelope',
      open && lanes >= 5 && json.includes('"run_id"'),
      `${lanes} lanes, ${json.length} chars of JSON`,
    );
    await context.close();
  }

  /* ---- pin + pinboard ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    await page.getByRole('button', { name: /Pin figure/ }).click();
    await page.waitForTimeout(600);
    await page.getByRole('button', { name: 'Pinboard' }).first().click();
    await page.waitForTimeout(800);
    const tiles = await page.locator('ul li').filter({ hasText: LOOKUP }).count();
    const text = await page.locator('main').innerText();
    const survived = await page.evaluate(
      () => JSON.parse(window.localStorage.getItem('ds-agent-pins') ?? '[]').length,
    );
    record(
      'pin → pinboard tile, persisted to localStorage',
      tiles > 0 && /on watch/i.test(text) && survived === 1,
      `${tiles} tile(s), ${survived} stored`,
    );
    await context.close();
  }

  /* ---- compare ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    await ask(page, ANOMALY);
    await page.getByRole('button', { name: /Compare/ }).first().click();
    await page.waitForTimeout(900);
    const text = await page.locator('main').innerText();
    const bands = ['Scope and route', 'Conclusion', 'Evidence', 'How it was computed', 'Run'];
    const present = bands.filter((b) => new RegExp(b, 'i').test(text));
    const pickers = await page.locator('main select').count();
    record(
      'compare aligns two answers band by band',
      present.length === bands.length && pickers === 2,
      `${present.length}/${bands.length} bands, ${pickers} pickers`,
    );
    await context.close();
  }

  /* ---- star + filters ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    await ask(page, ANOMALY);
    await ask(page, 'How did revenue in 2018 compare to 2017?');
    await page.keyboard.press('s');
    await page.waitForTimeout(600);
    const starredNow = await page.evaluate(
      () =>
        JSON.parse(window.localStorage.getItem('ds-agent-history') ?? '[]').filter(
          (e) => e.starred,
        ).length,
    );
    const allRows = await page.locator('nav[aria-label="Stored questions"] li').count();
    await page.getByRole('radio', { name: 'Starred' }).click();
    await page.waitForTimeout(400);
    const starredRows = await page.locator('nav[aria-label="Stored questions"] li').count();
    await page.getByRole('radio', { name: 'All' }).click();
    await page.getByRole('searchbox', { name: /Search stored questions/ }).fill('unusual');
    await page.waitForTimeout(400);
    const searchedRows = await page.locator('nav[aria-label="Stored questions"] li').count();
    record(
      'star (S) + rail filters + rail search',
      starredNow === 1 && starredRows === 1 && allRows === 3 && searchedRows === 1,
      `all ${allRows}, starred ${starredRows}, search "unusual" ${searchedRows}`,
    );
    await context.close();
  }

  /* ---- history persists across reload ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(600);
    const rows = await page.locator('nav[aria-label="Stored questions"] li').count();
    // And reopening it must restore the briefing from our own copy.
    await page.locator('nav[aria-label="Stored questions"] li button').first().click();
    await page.waitForTimeout(900);
    const reopened = await page
      .locator('section[aria-label="Verification"]')
      .isVisible()
      .catch(() => false);
    record(
      'history persists across reload and reopens the briefing',
      rows === 1 && reopened,
      `${rows} row(s) after reload`,
    );
    await context.close();
  }

  /* ---- shortcuts sheet ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await page.keyboard.press('?');
    const open = await page
      .locator('[aria-label="Keyboard shortcuts"]')
      .waitFor({ timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    const rows = await page.locator('[aria-label="Keyboard shortcuts"] dl > div').count();
    record('shortcuts sheet (?) lists the keyboard', open && rows >= 10, `${rows} bindings`);
    await context.close();
  }

  /* ---- theme atelier ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.waitForTimeout(400);

    const readAccent = () =>
      page.evaluate(() =>
        getComputedStyle(document.documentElement).getPropertyValue('--c-accent').trim(),
      );
    const champagne = await readAccent();
    await page.getByRole('radio', { name: /Platinum/ }).click();
    await page.waitForTimeout(400);
    const platinum = await readAccent();
    await page.getByRole('radio', { name: /Bronze/ }).click();
    await page.waitForTimeout(400);
    const bronze = await readAccent();

    await page.getByRole('radio', { name: /Compact/ }).click();
    await page.waitForTimeout(300);
    const density = await page.evaluate(() =>
      document.documentElement.getAttribute('data-density'),
    );
    const gap = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue('--gap-section').trim(),
    );
    await page.getByRole('radio', { name: /Reduced/ }).click();
    await page.waitForTimeout(300);
    const motion = await page.evaluate(() =>
      document.documentElement.getAttribute('data-motion'),
    );

    const distinct = new Set([champagne, platinum, bronze]).size === 3;
    record(
      'theme atelier: three accents, density, motion',
      distinct && density === 'compact' && motion === 'reduced',
      `accents ${champagne} / ${platinum} / ${bronze}; compact gap ${gap}`,
    );

    // And it has to survive a reload.
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const after = await page.evaluate(() => ({
      accent: document.documentElement.getAttribute('data-accent'),
      density: document.documentElement.getAttribute('data-density'),
      motion: document.documentElement.getAttribute('data-motion'),
    }));
    record(
      'atelier settings persist across reload',
      after.accent === 'bronze' && after.density === 'compact' && after.motion === 'reduced',
      JSON.stringify(after),
    );
    await context.close();
  }

  /* ---- tour ---- */
  {
    const { context, page } = await fresh({ tourSeen: false });
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    const open = await page
      .locator('[aria-label="Introduction"]')
      .waitFor({ timeout: 8_000 })
      .then(() => true)
      .catch(() => false);
    const spotlight = await page.locator('mask#tour-mask rect').count();
    let advanced = false;
    if (open) {
      const first = await page.locator('[aria-label="Introduction"] h2').innerText();
      await page.getByRole('button', { name: /^Next$|^Begin$/ }).click();
      await page.waitForTimeout(600);
      const second = await page
        .locator('[aria-label="Introduction"] h2')
        .innerText()
        .catch(() => '');
      advanced = second === '' || second !== first;
    }
    // Skip must dismiss it and remember that it did.
    const skip = page.getByRole('button', { name: 'Skip' });
    if (await skip.count()) await skip.click();
    await page.waitForTimeout(400);
    const seen = await page.evaluate(() =>
      window.localStorage.getItem('ds-agent-tour-seen'),
    );
    record(
      'first-run tour spotlights, advances, and is remembered',
      open && spotlight >= 2 && advanced && seen === 'seen',
      `${spotlight} mask rects`,
    );
    await context.close();
  }

  /* ---- J / K through history ---- */
  {
    const { context, page } = await fresh();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
    await ask(page, LOOKUP);
    await ask(page, ANOMALY);
    const before = await page.locator('h1').first().innerText();
    await page.keyboard.press('j');
    await page.waitForTimeout(900);
    const after = await page.locator('h1').first().innerText();
    record('J / K walk the history rail', before !== after, `"${before}" → "${after}"`);
    await context.close();
  }
}

/* ──────────────────────────────── 7. axe ──────────────────────────────── */

async function axe() {
  for (const theme of ['light', 'dark']) {
    for (const scene of ['hero', 'answer']) {
      const { context, page } = await fresh();
      await context.addInitScript(
        ([wantedTheme]) => {
          try {
            window.localStorage.setItem('ds-agent-theme', wantedTheme);
          } catch {
            /* private mode */
          }
        },
        [theme],
      );
      await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
      if (scene === 'answer') await ask(page, ANOMALY);
      await page.waitForTimeout(800);

      await page.evaluate(AXE);
      const run = await page.evaluate(() =>
        window.axe.run(document, {
          runOnly: {
            type: 'tag',
            values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'],
          },
          resultTypes: ['violations'],
        }),
      );
      // `minor` is advisory and is excluded by the project's standing gate.
      const serious = run.violations.filter((v) => v.impact !== 'minor');
      record(
        `axe: ${scene} (${theme})`,
        serious.length === 0,
        serious.length
          ? serious
              .map((v) => `${v.id}[${v.impact}] ${v.nodes[0]?.target.join(' ')}`)
              .join(' | ')
          : `0 violations, ${run.passes?.length ?? '?'} checks passed`,
      );
      await context.close();
    }
  }
}

/* ───────────────────── 8. V2: Track 5 surfaces (additive) ────────────────── */

/** Body text, whitespace-collapsed; SectionLabel uppercases through CSS. */
const bodyText = (page) => page.evaluate(() => document.body.innerText.replace(/\s+/g, ' '));

const V2_QUESTIONS = {
  why: 'Why did revenue drop in the top category in April 2018?',
  impact: 'How much did the April 2018 drop cost us?',
  forecast: 'Forecast revenue for the next 3 months',
  forecastLive: 'Forecast revenue in SP for the next 3 months',
  whatif: 'What if we raise prices 5%?',
  nowwhat: 'Why did August 2018 revenue fall, what did it cost, and what should we do?',
  discovery: 'What metrics do you have?',
  spikes: 'What are the spikes across all months?',
};

async function v2() {
  const { context, page, errors } = await fresh();
  await page.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });

  try {
    const chips = await page.locator('main ul li button').allInnerTexts();
    record('hero suggestions lead with WHY questions', /^Why\b/.test(chips[0] ?? '') && /^Why\b/.test(chips[1] ?? ''), chips.slice(0, 2).join(' | '));
  } catch (error) {
    record('hero suggestions lead with WHY questions', false, error.message.split('\n')[0]);
  }

  const facts = async () =>
    page.evaluate(() => ({
      kinds: [...document.querySelectorAll('[data-viz-kind]')].map((e) => e.getAttribute('data-viz-kind')),
      drawn: document.querySelectorAll('[data-testid="viz-card"] svg.recharts-surface').length,
      layouts: [...document.querySelectorAll('[data-layout]')].map((e) => e.getAttribute('data-layout')),
      plan: [...document.querySelectorAll('[data-plan-step]')].map((e) => e.getAttribute('data-state')),
      drivers: document.querySelectorAll('[data-testid="ranked-drivers"] li').length,
    }));

  const scenarios = [
    ['WHY: ranked drivers + waterfall + causal boundary', 'why', (f, text) =>
      f.layouts.includes('why') && f.drivers > 0 && f.kinds.includes('waterfall') && /causal boundary/i.test(text)],
    ['SO WHAT: impact range with its interval', 'impact', (f) => f.layouts.includes('impact') && f.kinds.includes('range_band')],
    ['FORECAST: fan with interval + method + backtest MAPE', 'forecast', (f, text) =>
      f.kinds.includes('forecast_fan') && /prediction interval/i.test(text) && /MAPE/.test(text) && /Fallback/i.test(text)],
    ['WHAT IF: scenario charts + assumptions', 'whatif', (f, text) =>
      f.layouts.includes('whatif') && f.drawn >= 2 && /scenario assumptions/i.test(text)],
    ['NOW WHAT: ranked actions with trade-offs', 'nowwhat', (f, text) =>
      f.layouts[0] === 'nowwhat' && /next actions/i.test(text)],
    ['DISCOVERY: catalog facts + example questions', 'discovery', (f, text) =>
      f.layouts.includes('discovery') && /example questions/i.test(text)],
    ['anomalies: flagged spikes and dips listed and marked', 'spikes', (f, text) =>
      f.kinds.includes('table') && /spike|dip/i.test(text)],
  ];
  for (const [name, key, check] of scenarios) {
    try {
      await ask(page, V2_QUESTIONS[key]);
      const f = await facts();
      const text = await bodyText(page);
      const done = f.plan.length > 0 && f.plan.every((state) => state !== 'pending' && state !== 'running');
      record(name, check(f, text) && done, `${f.layouts.join('+') || '—'} · ${f.kinds.join(',') || 'no charts'} · plan ${f.plan.length}`);
    } catch (error) {
      record(name, false, error.message.split('\n')[0]);
    }
  }

  // VZ-5 / 5.8: a forecast chart always shows its interval.
  try {
    await ask(page, V2_QUESTIONS.forecastLive);
    const fans = await page.locator('[data-viz-kind="forecast_fan"]').allInnerTexts();
    const before = (await facts()).kinds.length;
    await page.getByRole('button', { name: /Show trend and seasonality/ }).click();
    await page.waitForTimeout(900);
    const after = await facts();
    const badge = await page.locator('[data-plan-step]').allInnerTexts();
    record(
      'forecast: interval always drawn; trend + seasonality on request; plan badges',
      fans.length > 0 && fans.every((t) => /interval/i.test(t)) && after.kinds.length > before &&
        badge.some((t) => /Python · forecast/i.test(t)) && badge.some((t) => /Analytical table/i.test(t)),
      `${fans.length} fan(s), ${before} → ${after.kinds.length} charts`,
    );
  } catch (error) {
    record('forecast: interval always drawn; trend + seasonality on request; plan badges', false, error.message.split('\n')[0]);
  }

  // Live plan: the model step announces itself while it runs.
  try {
    await page.getByRole('textbox', { name: /Ask your data/ }).fill(V2_QUESTIONS.forecastLive);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => /Running model — this can take ~\d+ s/.test(document.body.innerText), undefined, { timeout: 15_000 });
    record('live plan view: "Running model — this can take ~N s"', true);
    await page.waitForFunction(() => /Pipeline · \d+ stages/i.test(document.body.innerText), undefined, { timeout: 30_000 });
  } catch (error) {
    record('live plan view: "Running model — this can take ~N s"', false, error.message.split('\n')[0]);
  }

  // Clarification: options, round, default; free text → round 2; an option → answered.
  try {
    await ask(page, 'Summarize revenue');
    const round1 = await page.getByTestId('clarify-round').innerText();
    const fallback = await page.getByTestId('clarify-default').innerText();
    const options = await page.locator('[data-testid="clarify-options"] li button').count();
    await page.getByPlaceholder(/missing metric or period/).fill('the usual one');
    await page.getByPlaceholder(/missing metric or period/).press('Enter');
    await page.waitForFunction(() => /Round 2 of 2/.test(document.body.innerText), undefined, { timeout: 30_000 });
    await page.waitForTimeout(1_200);
    await page.locator('[data-testid="clarify-options"] li button').first().click();
    await page.waitForSelector('[data-testid="feedback-bar"]', { timeout: 30_000 });
    const heading = await page.locator('h1').first().innerText();
    record(
      'clarify: option chips, "round 1 of 2", default stated, round 2, option answers',
      /Round 1 of 2/.test(round1) && /assumes/i.test(fallback) && options >= 2 && / — /.test(heading),
      `${options} options · ${heading}`,
    );
  } catch (error) {
    record('clarify: option chips, "round 1 of 2", default stated, round 2, option answers', false, error.message.split('\n')[0]);
  }

  // Conversation thread: a follow-up inherits, shows how it was read; New topic resets.
  try {
    await ask(page, 'revenue in SP in July 2018');
    await ask(page, 'What about RJ?');
    const chip = await page.getByTestId('interpreted-as').last().innerText();
    const thread = await page.getByTestId('conversation-thread').innerText();
    await page.getByTestId('new-topic').click();
    await ask(page, V2_QUESTIONS.impact);
    const after = await page.getByTestId('conversation-thread').innerText();
    record(
      'thread: turns + "interpreted as" chip; New topic starts cold',
      /Interpreted as/i.test(chip) && /Carried from/i.test(chip) && /earlier/i.test(thread) && !/earlier/i.test(after),
      chip.replace(/\s+/g, ' ').slice(0, 90),
    );
  } catch (error) {
    record('thread: turns + "interpreted as" chip; New topic starts cold', false, error.message.split('\n')[0]);
  }

  // Feedback: thumbs + reason, stored per answer.
  try {
    await page.getByRole('button', { name: 'Not useful' }).click();
    await page.locator('input[id^="feedback-reason"]').fill('wrong month');
    await page.getByRole('button', { name: 'Save reason' }).click();
    await page.waitForTimeout(300);
    const stored = await page.evaluate(() => window.localStorage.getItem('ds-agent-feedback') ?? '');
    const pressed = await page.getByRole('button', { name: 'Not useful' }).getAttribute('aria-pressed');
    record('feedback: thumbs + optional reason stored per answer', /"rating":"down"/.test(stored) && /wrong month/.test(stored) && pressed === 'true');
  } catch (error) {
    record('feedback: thumbs + optional reason stored per answer', false, error.message.split('\n')[0]);
  }

  // Replay: a past conversation, turn by turn, from the hero.
  try {
    // N returns to the hero, where stored conversations are offered for replay.
    await page.evaluate(() => (document.activeElement instanceof HTMLElement ? document.activeElement.blur() : null));
    await page.keyboard.press('n');
    await page.waitForSelector('[data-testid="conversation-list"]', { timeout: 10_000 });
    // The newest conversation (after New topic) has one turn; replay one with several.
    await page.locator('[data-testid="conversation-list"] button').filter({ hasText: /\b([2-9]|\d{2,}) turns/ }).first().click();
    const first = await page.getByTestId('replay-bar').innerText();
    await page.getByRole('button', { name: 'Next turn' }).click();
    const second = await page.getByTestId('replay-bar').innerText();
    record('replay: a past conversation steps turn by turn', /turn 1 of/.test(first) && /turn 2 of/.test(second), first.split('\n')[0]);
  } catch (error) {
    record('replay: a past conversation steps turn by turn', false, error.message.split('\n').filter((line) => /intercept|waiting for|Timeout/.test(line)).slice(0, 3).join(' / '));
  }

  const real = errors.filter((text) => !/404/.test(text));
  record('V2 mock flows: no console errors', real.length === 0, real.slice(0, 2).join(' | '));
  await context.close();

  // axe on the new surfaces, both themes, minor and best-practice included (5.6).
  for (const theme of ['light', 'dark']) {
    for (const [scene, question, expand] of [
      ['v2 why', V2_QUESTIONS.why, false],
      ['v2 forecast + components', V2_QUESTIONS.forecastLive, true],
      ['v2 clarify', 'Summarize revenue', false],
      ['v2 discovery', V2_QUESTIONS.discovery, false],
    ]) {
      const { context: ctx, page: p } = await fresh();
      await ctx.addInitScript(([t]) => {
        try { window.localStorage.setItem('ds-agent-theme', t); } catch { /* private mode */ }
      }, [theme]);
      try {
        await p.goto(`${BASE}/?mock=1`, { waitUntil: 'networkidle' });
        await ask(p, question);
        if (expand) {
          await p.getByRole('button', { name: /Show trend and seasonality/ }).click();
          await p.waitForTimeout(900);
        }
        await p.evaluate(AXE);
        const run = await p.evaluate(() =>
          window.axe.run(document, {
            runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'] },
            resultTypes: ['violations'],
          }),
        );
        record(
          `axe (incl. minor + best-practice): ${scene} (${theme})`,
          run.violations.length === 0,
          run.violations.length
            ? run.violations.map((v) => `${v.id}[${v.impact}] ${v.nodes[0]?.target.join(' ')}`).join(' | ')
            : `0 violations, ${run.passes?.length ?? '?'} checks passed`,
        );
      } catch (error) {
        record(`axe (incl. minor + best-practice): ${scene} (${theme})`, false, error.message.split('\n')[0]);
      }
      await ctx.close();
    }
  }
}

async function main() {
  browser = await chromium.launch();
  if (!wanted || wanted === 'mock') await mockStates();
  if (!wanted || wanted === 'features') await features();
  if (!wanted || wanted === 'axe') await axe();
  if (!wanted || wanted === 'v2') await v2();
  await browser.close();

  const failed = results.filter((r) => !r.pass);
  process.stdout.write(
    `\n${results.length - failed.length}/${results.length} passed\n`,
  );
  if (failed.length) {
    process.stdout.write('\nFAILURES\n');
    for (const f of failed) process.stdout.write(`  ${f.name} — ${f.note}\n`);
    process.exitCode = 1;
  }
}

await main();
