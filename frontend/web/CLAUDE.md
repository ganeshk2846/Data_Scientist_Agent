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
| `ink-faint` | `#8A857C` | metadata, labels |
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
| `ink-faint` | `#75706A` | metadata |
| `hairline` | `#2B2A27` | 1px borders |
| `hairline-strong` | `#3B3935` | emphasised borders |

Accent and data (one accent only — muted champagne gold):

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `gold` | `#B8975A` | `#C9A869` | the single accent; focus rings, claim marks, active states |
| `gold-soft` | `#DFCFA8` | `#6E5C38` | gold at low emphasis |
| `on-gold` | `#1C1B19` | `#121212` | text on a filled gold surface (6.2:1) |
| `--c-gold-wash` | `rgba(184,151,90,.10)` | `rgba(201,168,105,.12)` | active backgrounds, selection |
| `sage` | `#6B7F62` | `#8CA37F` | **positive** data only |
| `terracotta` | `#A85C45` | `#C47A5E` | **negative** data only |
| `series-1..4` | `#9A938A` `#B4ADA2` `#7D766E` `#C8C1B5` | same ramp, inverted | neutral data series |

Charts use gold, sage, terracotta and the warm-grey series ramp. Nothing else.

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

## 4. Accessibility

- Gold focus rings, 2px with 2px offset, via `:focus-visible`. Never remove an
  outline without replacing it with an equally visible one.
- WCAG AA contrast minimum for all text in both themes.
- Interactive elements are real `button`/`a`/`input` elements with accessible
  names. Decorative marks get `aria-hidden`.
- `Esc` closes every popover and overlay. Keyboard: `Ctrl/Cmd+K` focuses the
  question box, `Enter` submits.
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

`frontend/index.html` is the legacy UI. **Do not modify or delete it, and do
not reuse any of its colours** — it is a dark neon-blue design and violates
every rule above.

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

`envelopes.ts` holds eight scenarios covering all six statuses (three distinct
`answered` shapes: lookup, anomaly, driver). `transport.ts` satisfies the same
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
