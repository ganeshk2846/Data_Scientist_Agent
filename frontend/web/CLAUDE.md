# `frontend/web` — design and engineering rules

The premium frontend for `DS-AGENT-CORE`. **Read this file in full before
changing anything in this folder.** These rules are not suggestions; they were
set deliberately and approved.

---

## 0. The colour rule (strictest rule in this project)

**No purple, violet, lavender, indigo, magenta or pink. Anywhere. Ever.**

Not in colours, not in gradients, not in charts, not in shadows, not in glows,
not in focus rings, not in text selection, not in hover or active states. No
blue-to-purple gradients. No "just a hint of violet" in a shadow. If a library
ships a default palette containing any of these, override it explicitly.

Only the tokens in `src/index.css` may be used. Never hard-code a hex value in
a component — add or use a token. Recharts, in particular, must be passed
token colours explicitly; its defaults are not allowed.

### Allowed palette

Light theme:

| Token | Hex | Use |
| --- | --- | --- |
| `bg` | `#F7F4EE` | warm ivory page ground |
| `sunken` | `#F1EDE5` | left rail, recessed areas |
| `surface` | `#FDFBF7` | cards |
| `raised` | `#FFFFFF` | overlays, popovers |
| `ink` | `#1C1B19` | primary text |
| `ink-muted` | `#55524C` | secondary text |
| `ink-faint` | `#67625A` | metadata, labels (see the contrast note) |
| `hairline` | `#E2DCD0` | 1px borders |
| `hairline-strong` | `#CFC7B8` | emphasised borders, scrollbars |

Dark theme:

| Token | Hex | Use |
| --- | --- | --- |
| `bg` | `#121212` | onyx page ground |
| `sunken` | `#0D0D0C` | left rail |
| `surface` | `#1A1A18` | cards |
| `raised` | `#211F1C` | overlays |
| `ink` | `#F0EBE1` | warm off-white text |
| `ink-muted` | `#A8A29A` | secondary text |
| `ink-faint` | `#908B82` | metadata (see the contrast note) |
| `hairline` | `#2B2A27` | 1px borders |
| `hairline-strong` | `#3B3935` | emphasised borders |

Accent and data (one accent only — muted champagne gold):

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `gold` | `#B8975A` | `#C9A869` | the single accent; focus rings, claim marks, active states |
| `gold-soft` | `#DFCFA8` | `#6E5C38` | gold at low emphasis |
| `on-gold` | `#1C1B19` | `#121212` | text on a filled gold surface (6.2:1) |
| `gold-ink` | `#7A6134` | `#C9A869` | **gold used as TEXT** — see below |
| `--c-gold-wash` | `rgba(184,151,90,.10)` | `rgba(201,168,105,.12)` | active backgrounds, selection |
| `sage` | `#6B7F62` | `#8CA37F` | **positive** data only |
| `terracotta` | `#A85C45` | `#C47A5E` | **negative** data only |
| `series-1..4` | `#9A938A` `#B4ADA2` `#7D766E` `#C8C1B5` | same ramp, inverted | neutral data series |

Charts use gold, sage, terracotta and the warm-grey series ramp. Nothing else.

**`gold` vs `gold-ink`.** `gold` is tuned for strokes, fills, borders and rules.
As 11px text on a gold wash it measures **2.3:1** and fails AA, so all small
gold *type* — tags, claim ids, micro labels — uses `gold-ink`, which is a
darker champagne in light mode and the accent itself in dark. If you are
colouring text gold, you want `text-gold-ink`.

**`ink-faint` is contrast-tuned, not eyeballed.** It carries 11px metadata, so
it is set against the darkest ground it ever sits on — a gold wash over sunken
(`#EBE4D7`) — and clears 4.5:1 there. The earlier `#8A857C` measured 3.1:1 and
failed. Do not lighten it back.

Supporting tokens, all derived from the accent: `--c-grid` (the hero's
technical grid), `--c-edge` (the gold top-edge light used by `.edge-gold`),
`--c-sheen` (the cursor-following sheen used by `.sheen`), `--c-thread` (the
lineage highlight).

The one sanctioned place raw colour values appear outside `src/index.css` is
`src/hooks/useChartColors.ts`, which reads the tokens off the document at
runtime for Recharts and keeps a literal copy of the **light** palette as a
fallback for when `getComputedStyle` returns nothing. Keep those in sync with
the tokens; add nothing new there.

---

## 1. Design direction

"Private bank meets editorial luxury." Posh, calm, expensive. **Not** a
neon-gradient AI dashboard.

- Generous whitespace. Let sections breathe; under-fill rather than over-fill.
- Hairline **1px** borders, never 2px or heavier for structure.
- Soft **layered** shadows (`shadow-soft`, `shadow-lifted`, `shadow-overlay`),
  warm-tinted, never coloured.
- Subtle paper-grain texture, applied once via `.paper-grain` on the shell.
- **Glass blur only on overlays** — the top bar, popovers, mobile scrims.
  Never on cards or content surfaces.
- Status reads through small marks (dots, hairlines, micro labels), not through
  large blocks of colour.

## 2. Typography

| Family | Role |
| --- | --- |
| **Fraunces** (fallback Cormorant Garamond) | headings, the answer narrative, headline figures |
| **Inter Tight** (fallback Manrope) | all UI text, labels, buttons, tables |
| **JetBrains Mono** | SQL, run ids, raw contract values |

Type scale (Tailwind names in `tailwind.config.ts`):

| Name | Size / line-height | Use |
| --- | --- | --- |
| `display` | 56 / 60, −0.02em | hero headline |
| `figure` | 44 / 48 | headline numbers |
| `h1` | 38 / 44, −0.015em | conclusion narrative |
| `h2` | 26 / 34 | section heads |
| `h3` | 18 / 26 (sans, 500) | card titles |
| `body-serif` | 17 / 30 | long-form narrative |
| `body` | 15 / 24 | interface prose |
| `small` | 13 / 20 | metadata |
| `micro` | 11 / 16, 0.08em, uppercase | badges, labels, footer strip |

**Every number is tabular.** Use `tabular-nums` (or the `.tnum` class); the base
layer already applies it to `th`, `td`, `input`, `code` and `pre`. Format
numbers through `src/lib/format.ts` — never with bare `toString()`.

## 3. Motion

- Slow and smooth: **300–600ms**. `duration-micro` (300), `duration-reveal`
  (450), `duration-draw` (600).
- `ease-editorial` = `cubic-bezier(.22,.61,.36,1)`. For Framer Motion springs
  use `{ stiffness: 120, damping: 24 }` — critically damped, **never bouncy**.
  No overshoot, no `type: 'spring'` with low damping, no `backOut`.
- Respect `prefers-reduced-motion`: CSS is handled globally in `index.css`;
  for Framer Motion, read `useReducedMotion()` and skip the animation.

## 3a. Signature craft

These are the details that make the product feel made rather than assembled.
They are cheap to break and hard to notice breaking, so they are listed here.

| Device | Where | How |
| --- | --- | --- |
| **Technical grid** | hero only | `TechnicalGrid` — two drifting rules (24px and 120px) on independent cycles, radially masked so it has no visible edge. Frozen under reduced motion. |
| **Glass plinth** | hero ask box | translucent surface + `backdrop-blur-xl` + `.edge-gold`. Its gold border **traces itself** on focus: one SVG rect with `pathLength={1}` whose `strokeDashoffset` animates 1 → 0 over 600ms. |
| **Gold top edge** | cards, palette, plinth | `.edge-gold` — a 1px gradient brightest at the centre, lifting to full on hover. |
| **Cursor sheen** | hero plinth, evidence cards | `.sheen` + `useSheen`, which writes `--mx`/`--my` in one rAF per frame. |
| **Travelling light** | live pipeline | a point of gold runs the hairline between a finished stage and the one still running. |
| **Count-up** | single-value evidence | `CountUp`, ease-out quint. See the SAFE-8 note below. |
| **Lineage thread** | claim ↔ evidence ↔ query | `LineageProvider`; hovering or focusing any one lights all three. |

Glass blur remains overlay-only: top bar, palette, popovers, scrims, the
floating composer, the plinth. Never on a plain content card.

## 3b. The frontend computes nothing (SAFE-8)

The interface displays what the `AnswerEnvelope` contains. It does not derive,
aggregate, re-round or infer a single figure.

- `CountUp` animates the *presentation* of a value the envelope already holds.
  Its final frame is that value through `formatNumber`, intermediate frames are
  `aria-hidden`, and the accessible name is the final value from first render.
- Follow-up questions (`lib/followUps.ts`) are **templates** filled from
  `scope.metric` and `scope.window` only. They contain no number, finding or
  insight of ours, and the file returns nothing rather than offer a question
  the backend cannot answer.
- `TrustPanel` reports only what the envelope evidences. A check means the
  envelope positively says so; a dash means it does not say, and we show a dash
  rather than imply a pass.
- `briefingToMarkdown` transcribes. If a field is absent, its section is
  omitted — never filled in.

## 4. Accessibility

- Gold focus rings, 2px with 2px offset, via `:focus-visible`. Never remove an
  outline without replacing it with an equally visible one.
- WCAG AA contrast minimum for all text in both themes.
- Interactive elements are real `button`/`a`/`input` elements with accessible
  names. Decorative marks get `aria-hidden`.
- Keyboard: **`Ctrl/Cmd+K` opens the command palette** (it no longer focuses
  the question box — the palette is the one entry point for asking and for
  every action), `Enter` submits, `Shift+Enter` adds a newline, `P` enters
  presentation mode, `Esc` closes every overlay. Single-letter shortcuts are
  ignored while typing and with any modifier held.
- **Prefer content-derived accessible names over `aria-label`.** A label that
  restates visible text can only drift from it; where both exist they must
  agree (axe's `label-content-name-mismatch`). The claim superscript is the
  worked example: the `<sup>` is `aria-hidden` and the detail is `sr-only`
  text *inside* the button, so the name is built from the button's own content.
- Any element with its own scrollbar needs `tabIndex={0}` and a label, or a
  keyboard user cannot scroll it.
- `<dt>`/`<dd>` must be direct children of the `<dl>` or of a **single**
  wrapping `<div>`. Decorations go inside the `<dt>`, positioned absolutely —
  not as another nesting level.
- Skeleton loaders are shaped like the content that replaces them, so there is
  **no layout shift**. Skeletons are `aria-hidden`.

## 5. Backend contract rules

The backend is **frozen**. Never change anything under `backend/`, and never
require a CORS change — the Vite dev server proxies `/api` to
`http://127.0.0.1:8000`.

### Endpoints

| Call | Notes |
| --- | --- |
| `POST /api/ask` | `{question, session_id, clarification_of?}` → `{contract_version, run_id}` |
| `GET /api/runs/{id}/events` | SSE. Reconnect with `Last-Event-ID: <seq>`. |
| `GET /api/runs/{id}` | The `AnswerEnvelope`, **or HTTP 202** `{contract_version, run_id, status:"running"}` while it is still building. |

`GET /api/runs/{id}` blocks **up to 15 s server-side** (`wait_for_envelope`)
before it returns 202. Use a 10 s client abort, then back off
400/800/1600/3200 ms (capped) with a ~60 s overall deadline.

### SSE events — exactly five types, no others

Derived from the `_emit` calls in `backend/src/service.py`. **Never invent an
event type or a stage the backend does not emit.**

| Type | Fields | Terminal |
| --- | --- | --- |
| `step_started` | `step`, `component`, `at` | no |
| `step_finished` | `step`, `component`, `status` (`ok`/`failed`), `duration_ms`, `summary` | no |
| `clarify` | `what_understood`, `what_needs_clarification` | **no** |
| `answer` | `status` | **yes** |
| `error` | `error: {code, message, retriable}` | **yes** |

All events also carry `type`, `seq`, `run_id`. The SSE `id` is `seq`; the SSE
`event` is `type`, so named listeners are required — a bare `onmessage` will
receive nothing.

`clarify` is **not terminal**. It is followed by an `answer` event with
`status: "clarify"`. Keep the stream open until `answer` or `error`.

### Pipeline stages — exactly seven

| Step | `component` | Emitted |
| --- | --- | --- |
| `1` | `Guard` | always |
| `2` | `Router and Extractor` | always |
| `7` | `SQL Compiler` | only when the primary route is `lookup`/`anomaly`/`driver` |
| `9` | `Executor` | same condition as step 7 |
| `11` | `Analysts` | only when the orchestrator produced analyst outputs |
| `12` | `Evidence Ledger` | always |
| `14` | `Fact Checker` | always |

Step ids are sparse because they are positions in the full design DAG. The
registry lives in `src/lib/stages.ts`; it is the only place stages are defined.
The legacy `frontend/index.html` guesses at resolver/validator/reconciler
stages that are never emitted — do not copy it.

### Known contract gaps (approved handling)

| # | Gap | What we do |
| --- | --- | --- |
| 1 | `next_actions` is hardcoded `()` in `build_answer_envelope` | Build `NextActionCard` to spec but **render the section only when non-empty**. Never invent actions. Visible in mock mode only. |
| 2 | `refusal.closest_answerable` is never populated | Render conditionally; when absent show only `missing`. |
| 3 | `AnomalyResult` carries no time series | Use a sibling `lookup` evidence block's series when it has a time-role column plus a measure. Otherwise fall back to a **horizontal range bar** — shaded `expected_range` band, a tick for `expected`, a marked point for `actual`, `deviation_pct` labelled. **Never draw a one-point line chart.** |
| 4 | `EvidenceBlock.output` is `Any` | Narrow by `module` via our own union in `src/types/envelope.ts` and validate defensively. For `anomaly`/`driver` the payload is a full `AnalystOutput` dump, so the result is at `output.result`. For `lookup` it is an ad-hoc dict with no model behind it. |
| 5 | `clarify` treated as terminal by the old UI | See above — it is not. |
| 7 | The 202 body is not an envelope | Typed separately as `RunPending`. |
| 8 | `route.confidence` is effectively 0.70–1.00 (the `RouterResult` validator rejects less) | Scale the gauge **0.5–1.0**, and **always show the exact numeric confidence beside it**. |
| 9 | `_error_envelope` sets a false `route.labels=("blocked",)` with confidence 0 | **Suppress the route strip and gauge entirely when `status === "error"`.** |
| 10 | `scope.data_range`, `est_cost`, `repair_of` are never set | Render only when present. |
| 11 | `origin` is stamped per run, not per query | Show the SQL origin badge **once at run level**, not on each query card. |
| 12 | There is no `/api/health` | Probe `GET /api/runs/__probe__`: a network failure means offline, a 404 means online. |
| 13 | `GET /` serves the legacy `frontend/index.html` | Out of scope. This app runs on the Vite dev server. Serving the built bundle would need a backend change. |
| 14 | **The driver path raises.** Every driver question returns `error`: `backend/src/orchestrator.py` fails with `_contribution_table() got multiple values for argument 'current'`. Reproduced directly against the orchestrator. | `DriverBars` is built to contract and verified against mock data, but is unreachable live. Do not put a driver question in the suggestion chips. Fixing it means changing `backend/`, which is out of scope. |
| 15 | Lookup measures are declared with the bare column type `"number"`, which matches no SQL type name | `deriveSeries` treats the declared type as a hint only and falls back to sniffing whether the column actually holds numbers. Without this, live anomaly runs lost their series and dropped to the range-bar fallback. |

### Verified suggestion chips

The four hero chips in `src/components/ask/SuggestionChips.tsx` are **verified to
return a full `answered` briefing** against the live backend. Re-verify before
changing any of them:

| Chip | Route | Shape |
| --- | --- | --- |
| How many orders were there in August 2018? | `lookup` | 1 query, 1 claim, 6 stages |
| Why did revenue spike in November 2017? | `anomaly`, `driver` | anomaly `unusual`, 14-point series, 7 stages |
| How did revenue in 2018 compare to 2017? | `lookup` | 2 queries, 3 claims, comparative narrative |
| Was order count unusual in August 2018? | `anomaly`, `driver` | anomaly `within_normal_range`, 23-point series |

Two rules learned from probing the live backend:

- The **anomaly** route only answers when the question names both a governed
  metric (`gmv`, `revenue`, `order_count`, `aov`) and an explicit window
  **including the year**. "Why did revenue drop in August?" clarifies; "…in
  August 2018?" answers.
- The **driver** route additionally needs a dimension — and then still raises
  (gap 14), so it cannot be demonstrated live at all.

`frontend/index.html` is the legacy UI. **Do not modify or delete it, and do
not reuse any of its colours** — it is a dark neon-blue design and violates
every rule above.

## 5a. Product surfaces

| Surface | File | Note |
| --- | --- | --- |
| Command palette | `components/palette/CommandPalette.tsx` | Ask, reopen a past answer, and the few actions worth a keystroke. Substring matching over a short curated list — not fuzzy, because predictability is what makes a palette feel fast. Free text is always offered as a question. |
| How this was computed | `components/queries/QueryList.tsx` | The SQL is a first-class section directly under the conclusion, **expanded by default** — the product's whole promise is that you can check the arithmetic. Line-numbered gutter, hand-rolled highlighter (every library ships a purple theme), copy with a drawn-on tick. |
| Lineage | `components/briefing/LineageContext.tsx` | Derived strictly from `claim.source.id` and `evidence[].source_claims`. It never invents a relationship the backend did not assert. |
| Hero figures | `lib/evidenceTitle.ts` | A lookup returning exactly one row and one column is a headline number, not a table. Titles come from `scope`, never from reading the data — and a comparative run's two identical titles are disambiguated by position, because `scope` only carries the current window. |
| Follow-ups | `lib/followUps.ts` | See SAFE-8 above. Governed metrics only, window must include the year. |
| Export | `lib/exportBriefing.ts`, print block in `index.css` | "Copy as briefing" is Markdown; "Download PDF" is the browser's own print dialogue against the print stylesheet — the most reliable PDF route, no library, no sandbox exception. `data-print="hide" / "show" / "flow"` control what the printed report does. |
| Presentation mode | `components/PresentationMode.tsx` | Renders the **same** `Briefing` with `presenting`, so there is exactly one place the answer is designed. |

## 6. Status handling

Every `RunStatus` gets a designed state, never a bare error string:
`answered`, `clarify` (what was understood + what needs clarifying, with a
reply box that re-asks with `clarification_of`), `refused` (missing +
`closest_answerable` as a clickable suggestion), `blocked`,
`insufficient_evidence`, `error`, plus a **backend-offline** state.

## 7. Mock mode

`?mock=1` serves realistic sample `AnswerEnvelope`s for **every** status and a
simulated event stream, so the design can be reviewed with no backend running.
Mock data lives in `src/lib/mock/` and must stay contract-accurate — it is the
only place `next_actions` and `closest_answerable` are ever populated.

`envelopes.ts` holds nine scenarios covering all six statuses (four distinct
`answered` shapes: lookup, comparative, anomaly, driver). `transport.ts` satisfies the same
`RunTransport` interface as the live transport, so `useRun` is identical in both
modes, and its simulated stream respects the conditional stages — a clarify run
emits no step 7, 9 or 11, because the real backend would not either.
`pickScenario` routes the four hero suggestion chips to the same statuses the
live backend actually returns for them (verified: lookup → answered, August
revenue → clarify, shipping delays → clarify, revenue by state → error).

Under `?mock=1` a `MockBar` lists every scenario as a chip, so each designed
state is one click away.

## 8. Code conventions

- TypeScript **strict**, plus `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes` and `verbatimModuleSyntax`. Type-only imports
  use `import type`.
- `@/` aliases `src/` (declared in both `tsconfig.app.json` and
  `vite.config.ts`).
- Types mirror the Pydantic models exactly: `tuple[X, ...]` → `readonly X[]`,
  `X | None` → `X | null` (present-and-null, not optional).
- One component per file, named after the file. Keep `src/lib` free of React.
- Comments explain *why*, at the density of the surrounding code.

## 8a. Quality gates

Both must be clean before committing. The accessibility gate is not optional:
the colour and contrast tokens were set *from* its measurements.

```bash
npm run typecheck      # strict; must stay clean
npm run build          # must stay clean
# the colour rule, mechanically:
grep -rniE "purple|violet|lavender|indigo|magenta|pink|fuchsia" src/
```

The last command should match only the comment lines that *state* the rule.

Screenshots and the axe audit are driven with Playwright against the dev server
in mock mode, in both themes, at desktop and mobile widths. Current status:
**0 axe violations** (wcag2a/2aa/21a/21aa, minor excluded) across hero, answer
and palette in both themes, and **0 console errors**.

## 9. Commands

```bash
cd frontend/web
npm install
npm run dev        # http://localhost:5173, proxies /api to 127.0.0.1:8000
npm run typecheck  # strict, must stay clean
npm run build
```

Backend, from the repo root:

```bash
uvicorn app:app --app-dir backend/src --reload
```
