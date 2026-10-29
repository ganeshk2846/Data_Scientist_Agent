/**
 * The design and accessibility gate.
 *
 * Drives the dev server in mock mode with Playwright, walks every surface in
 * both themes at desktop and mobile widths, writes a screenshot of each, and
 * runs axe over it. Console errors are failures too: a design review of a page
 * that is throwing is a review of the wrong page.
 *
 *   node scripts/audit.mjs                 # everything
 *   node scripts/audit.mjs --only=hero     # one scene, by id
 *   node scripts/audit.mjs --no-axe        # screenshots only, much faster
 *
 * Output lands in `scripts/shots/`, which is git-ignored.
 */

import { readFileSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

const HERE = dirname(fileURLToPath(import.meta.url));
const SHOTS = join(HERE, 'shots');
const BASE = process.env.BASE_URL ?? 'http://localhost:5173';
const AXE = readFileSync(
  join(HERE, '..', 'node_modules', 'axe-core', 'axe.min.js'),
  'utf8',
);

const args = process.argv.slice(2);
const only = args.find((arg) => arg.startsWith('--only='))?.slice('--only='.length);
const skipAxe = args.includes('--no-axe');

/** The question each scene asks, and what it has to do once answered. */
const LOOKUP = 'How many orders were there in August 2018?';
const ANOMALY = 'Was order count unusual in August 2018?';

/**
 * Scenes. `act` runs against the page once it has loaded; `wait` is a selector
 * that must be present before the shot is taken, so nothing is captured
 * mid-reveal.
 */
const SCENES = [
  {
    id: 'hero',
    url: '/?mock=1',
    wait: 'h1',
  },
  {
    id: 'builder',
    url: '/?mock=1',
    wait: 'text=The question',
    async act(page) {
      await page.getByRole('button', { name: /Build a question/ }).click();
      await page.getByRole('radio', { name: 'GMV' }).click();
      await page.getByRole('radio', { name: 'Unusual?' }).click();
    },
  },
  {
    id: 'live-run',
    url: '/?mock=1',
    wait: 'text=Running',
    async act(page) {
      await page.getByRole('textbox', { name: /Ask your data/ }).fill(ANOMALY);
      await page.keyboard.press('Enter');
      await page.waitForTimeout(900);
    },
    settle: 0,
  },
  {
    id: 'answer',
    url: '/?mock=1',
    wait: 'section[aria-label="Verification"]',
    async act(page) {
      await askAndSettle(page, LOOKUP);
    },
  },
  {
    id: 'answer-anomaly',
    url: '/?mock=1',
    wait: 'section[aria-label="Verification"]',
    async act(page) {
      await askAndSettle(page, ANOMALY);
    },
  },
  {
    id: 'sql',
    url: '/?mock=1',
    wait: 'text=How this was computed',
    async act(page) {
      await askAndSettle(page, LOOKUP);
      await page.locator('text=How this was computed').first().scrollIntoViewIfNeeded();
    },
  },
  {
    id: 'inspector',
    url: '/?mock=1',
    wait: 'text=Run inspector',
    async act(page) {
      await askAndSettle(page, ANOMALY);
      await page.getByRole('button', { name: /Inspect run/ }).click();
      await page.waitForTimeout(500);
    },
  },
  {
    id: 'pinboard',
    url: '/?mock=1',
    wait: 'text=on watch',
    async act(page) {
      await askAndSettle(page, LOOKUP);
      await page.getByRole('button', { name: /Pin figure/ }).click();
      await goToView(page, 'Pinboard');
    },
  },
  {
    id: 'pinboard-empty',
    url: '/?mock=1',
    wait: 'text=Nothing pinned yet',
    async act(page) {
      await goToView(page, 'Pinboard');
    },
  },
  {
    id: 'compare',
    url: '/?mock=1',
    wait: 'text=Two answers, aligned',
    async act(page) {
      await askAndSettle(page, LOOKUP);
      await askAndSettle(page, ANOMALY);
      await goToView(page, /Compare/);
    },
  },
  {
    id: 'palette',
    url: '/?mock=1',
    wait: '[aria-label="Command palette"]',
    async act(page) {
      await page.keyboard.press('Control+k');
      await page.waitForTimeout(400);
    },
  },
  {
    id: 'shortcuts',
    url: '/?mock=1',
    wait: '[aria-label="Keyboard shortcuts"]',
    async act(page) {
      await page.keyboard.press('?');
      await page.waitForTimeout(400);
    },
  },
  {
    id: 'tour',
    url: '/?mock=1&tour=1',
    wait: '[aria-label="Introduction"]',
    async act(page) {
      await page.waitForTimeout(1_400);
    },
  },
  {
    id: 'settings',
    url: '/?mock=1',
    wait: '[aria-label="Settings"]',
    async act(page) {
      await page.getByRole('button', { name: 'Settings' }).click();
      await page.waitForTimeout(400);
    },
  },
  {
    id: 'clarify',
    url: '/?mock=1',
    wait: 'text=One detail short of an answer',
    async act(page) {
      await askAndSettle(page, 'Why did revenue drop in August?');
    },
  },
  {
    id: 'refused',
    url: '/?mock=1',
    wait: 'text=cannot be answered',
    async act(page) {
      await askAndSettle(page, 'Which accounts have elevated churn risk next quarter?');
    },
  },
  {
    id: 'table',
    url: '/?mock=1',
    wait: 'text=Export CSV',
    async act(page) {
      await askAndSettle(page, 'Was order count unusual in August 2018?');
      await page.getByRole('radio', { name: 'Table' }).first().click();
      await page.waitForTimeout(400);
    },
  },
];

/**
 * The rail is a sticky column on desktop and a drawer on mobile, so a scene
 * that navigates has to open it first on a narrow viewport. Without this the
 * nav button is outside the viewport and the click never lands.
 */
async function goToView(page, name) {
  const toggle = page.getByRole('button', { name: 'Toggle the rail' });
  if (await toggle.isVisible()) {
    await toggle.click();
    await page.waitForTimeout(450);
  }
  await page.getByRole('button', { name }).first().click();
  await page.waitForTimeout(650);
}

async function askAndSettle(page, question) {
  const box = page.getByRole('textbox', { name: /Ask your data/ });
  await box.fill(question);
  await page.keyboard.press('Enter');
  // The mock stream runs ~3 s; the envelope collect adds ~0.4 s.
  await page.waitForTimeout(4_600);
}

const VIEWPORTS = [
  { id: 'desktop', width: 1440, height: 1000 },
  { id: 'mobile', width: 390, height: 844 },
];

const THEMES = ['light', 'dark'];

const findings = [];

async function runAxe(page, label) {
  if (skipAxe) return;
  await page.evaluate(AXE);
  const result = await page.evaluate(async () =>
    window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      resultTypes: ['violations'],
    }),
  );
  for (const violation of result.violations) {
    // `minor` is advisory and is excluded by the project's standing gate.
    if (violation.impact === 'minor') continue;
    findings.push({
      scene: label,
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      nodes: violation.nodes.slice(0, 3).map((node) => node.target.join(' ')),
    });
  }
}

async function main() {
  rmSync(SHOTS, { recursive: true, force: true });
  mkdirSync(SHOTS, { recursive: true });

  const browser = await chromium.launch();
  const consoleErrors = [];

  for (const viewport of VIEWPORTS) {
    for (const theme of THEMES) {
      // Mobile only gets the scenes that read differently narrow; the rest
      // would be fifteen more near-identical columns to review.
      const scenes = SCENES.filter(
        (scene) =>
          (!only || scene.id === only) &&
          (viewport.id === 'desktop' ||
            ['hero', 'answer', 'pinboard', 'compare', 'inspector', 'sql'].includes(
              scene.id,
            )),
      );

      for (const scene of scenes) {
        const context = await browser.newContext({
          viewport: { width: viewport.width, height: viewport.height },
          colorScheme: theme,
          deviceScaleFactor: 2,
          reducedMotion: 'no-preference',
        });
        // The theme is stored, not inferred, so stamp it before the app boots.
        await context.addInitScript(
          ([wanted]) => {
            try {
              window.localStorage.setItem('ds-agent-theme', wanted);
            } catch {
              /* private mode; the colorScheme emulation still applies */
            }
          },
          [theme],
        );
        // Every scene but the tour starts with the tour already dismissed.
        if (scene.id !== 'tour') {
          await context.addInitScript(() => {
            try {
              window.localStorage.setItem('ds-agent-tour-seen', 'seen');
            } catch {
              /* as above */
            }
          });
        }

        const page = await context.newPage();
        const label = `${scene.id}-${theme}-${viewport.id}`;
        page.on('console', (message) => {
          if (message.type() === 'error') {
            consoleErrors.push(`${label}: ${message.text()}`);
          }
        });
        page.on('pageerror', (error) => {
          consoleErrors.push(`${label}: ${error.message}`);
        });

        try {
          await page.goto(`${BASE}${scene.url}`, { waitUntil: 'networkidle' });
          if (scene.act) await scene.act(page);
          if (scene.wait) {
            await page.locator(scene.wait).first().waitFor({ timeout: 15_000 });
          }
          // Let the last reveal land, so nothing is shot mid-transition.
          await page.waitForTimeout(scene.settle ?? 900);

          await page.screenshot({
            path: join(SHOTS, `${label}.png`),
            fullPage: viewport.id === 'desktop' && !scene.wait?.startsWith('['),
          });
          await runAxe(page, label);
          process.stdout.write(`  ok  ${label}\n`);
        } catch (error) {
          process.stdout.write(`FAIL  ${label}  ${error.message.split('\n')[0]}\n`);
          findings.push({ scene: label, id: 'scene-failed', help: error.message });
          await page
            .screenshot({ path: join(SHOTS, `${label}-FAILED.png`) })
            .catch(() => {});
        }

        await context.close();
      }
    }
  }

  await browser.close();

  const report = { findings, consoleErrors };
  writeFileSync(join(SHOTS, 'report.json'), JSON.stringify(report, null, 2));

  process.stdout.write(`\naxe violations: ${findings.length}\n`);
  for (const finding of findings) {
    process.stdout.write(
      `  ${finding.scene} · ${finding.id} · ${finding.impact ?? ''} · ${finding.help}\n` +
        (finding.nodes ? `      ${finding.nodes.join('\n      ')}\n` : ''),
    );
  }
  process.stdout.write(`console errors: ${consoleErrors.length}\n`);
  for (const error of consoleErrors.slice(0, 20)) {
    process.stdout.write(`  ${error}\n`);
  }

  if (findings.length > 0 || consoleErrors.length > 0) process.exitCode = 1;
}

await main();
