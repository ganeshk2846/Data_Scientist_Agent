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
| `sunken` | `#F1EDE5` | left rail, recessed areas, pickers |
| `surface` | `#FDFBF7` | cards |
| `raised` | `#FFFFFF` | overlays, popovers |
| `high` | `#FFFFFF` | a panel floating *above* an overlay (toasts, the palette) |
| `ink` | `#1C1B19` | primary text |
| `ink-muted` | `#55524C` | secondary text |
| `ink-faint` | `#67625A` | metadata, labels (see the contrast note) |
| `hairline` | `#E2DCD0` | 1px borders |
| `hairline-strong` | `#CFC7B8` | emphasised borders, scrollbars |

Dark theme — **five stepped onyx tones, never flat black.** `#0C0C0B` is the
floor and each step up is a deliberate lift in luminance, so a card reads as a
card and an overlay above it still reads as above it:

| Token | Hex | Use |
| --- | --- | --- |
| `bg` | `#141413` | onyx page ground |
| `sunken` | `#0C0C0B` | left rail, recessed areas |
| `surface` | `#1C1C1A` | cards |
| `raised` | `#252421` | overlays |
| `high` | `#2E2D29` | above an overlay |
| `ink` | `#F0EBE1` | warm off-white text |
| `ink-muted` | `#A8A29A` | secondary text |
| `ink-faint` | `#908B82` | metadata (see the contrast note) |
| `hairline` | `#2D2C29` | 1px borders |
| `hairline-strong` | `#3E3C38` | emphasised borders |

Data semantics — unchanged, and still the only colours that carry meaning:

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `sage` | `#6B7F62` | `#8CA37F` | **positive** data only; strokes and fills |
| `sage-ink` | `#5B6B52` | `#8CA37F` | **sage used as TEXT** — see below |
| `terracotta` | `#A85C45` | `#C47A5E` | **negative** data only |
| `series-1..4` | `#9A938A` `#B4ADA2` `#7D766E` `#C8C1B5` | same ramp, inverted | neutral data series |

Charts use the accent, sage, terracotta and the warm-grey series ramp. Nothing
else.

### The accent, and its three variants

The accent used to be one colour called `gold`. It is now **one accent at a
time, chosen from three**, so every token is named `accent*` — there is no
`gold` anything left, and a PR that reintroduces the name is wrong.

| Variant | `data-accent` | Light | Dark | Character |
| --- | --- | --- | --- | --- |
| **Champagne Gold** (default) | `champagne` | `#B8975A` | `#C9A869` | the house accent |
| **Platinum** | `platinum` | `#808A92` | `#ADB6BE` | cool silver-grey |
| **Bronze** | `bronze` | `#B77E53` | `#CB8F63` | warm copper |

Each variant sets **exactly four values**:

| Token | Use |
| --- | --- |
| `--c-accent` | the accent; focus rings, claim marks, the one live element |
| `--c-accent-soft` | the accent at low emphasis |
| `--c-on-accent` | text on a filled accent surface (measured ≥ 4.8:1 for all three) |
| `--c-accent-ink` | **the accent used as TEXT** — see below |

Everything else is **derived** from `--c-accent` in one place, so a variant can
never leave a stray swatch of the old accent behind:

```css
--c-accent-wash: rgb(var(--c-accent) / 0.10);   /* active backgrounds, selection */
--c-grid:        rgb(var(--c-accent) / 0.16);   /* the hero's technical grid */
--c-edge:        rgb(var(--c-accent) / 0.42);   /* the .edge-accent top light */
--c-sheen:       rgb(var(--c-accent) / 0.055);  /* the cursor-following sheen */
--c-thread:      rgb(var(--c-accent) / 0.55);   /* the lineage highlight */
```

Adding a fourth variant therefore means adding four values and nothing else.
**Never hard-code a derived value** — if you find yourself writing
`rgba(184,151,90,…)`, you have just pinned the page to champagne.

**`accent` vs `accent-ink`, and `sage` vs `sage-ink`.** The stroke colour is
not the type colour. `accent` is tuned for strokes, fills, borders and rules;
as 11px text on an accent wash it measures **2.3:1** and fails AA, so all small
accent *type* — tags, claim ids, micro labels — uses `accent-ink`. Sage has the
same split for the same reason: `#6B7F62` as 13px type on sunken measures
**3.7:1** and failed the axe gate, so `sage-ink` (`#5B6B52`, 4.95:1 there)
carries sage type. If you are colouring text, you want the `-ink` token.

**`ink-faint` is contrast-tuned, not eyeballed.** It carries 11px metadata, so
it is set against the darkest ground it ever sits on — an accent wash over
sunken (`#EBE4D7`) — and clears 4.5:1 there. The earlier `#8A857C` measured
3.1:1 and failed. Do not lighten it back.

### The accent is jewellery

One accented element per screen, and it is the thing that matters on *that*
screen. This is a rule, not a preference, and most of the product is
deliberately accent-free:

- `.edge-accent` (the accent top-edge light) belongs to the **single focal
  element**: the hero plinth, the conclusion card, the command palette, the
  shortcuts sheet, the tour card. Nothing else.
- Every other card uses **`.edge-light`** — a *neutral* `--c-lift` highlight on
  its own top edge. It is almost invisible, and that is the point: it is what
  stops a card reading as a flat rectangle of fill.
- SQL keywords are **ink at medium weight**, not accent. A query is a field of
  a hundred keywords, and an accent spread over a hundred things is not an
  accent.
- A **finished** pipeline stage is struck in ink; only the stage that is
  *running* wears the accent. On a live track that leaves exactly one accented
  element travelling down the instrument.
- The confidence arc is ink: it sits on the conclusion card, where the sentence
  is the focal point, and a second accent there would compete.

### What is NOT a palette colour

Four raw values are allowed outside the tokens, and only these:

- `#000` / `#fff` inside an **SVG mask or a radial mask gradient** (the hero
  grid's edge fade, the tour's spotlight hole). These are *luminance* values
  that drive a mask channel; they never paint a pixel.
- `#ffffff` as the fallback ground when rasterising a chart to PNG, where the
  real value comes from the page's own computed `background-color`.
- `src/hooks/useChartColors.ts` keeps a literal copy of the **light champagne**
  palette as a fallback for when `getComputedStyle` returns nothing. Keep it in
  sync with the tokens; add nothing new there.

### Auditing the rule

The name grep is necessary but not sufficient — it cannot catch a purple *hex*.
Both checks must be clean:

```bash
# 1. the names
grep -rniE "purple|violet|lavender|indigo|magenta|pink|fuchsia" src/
# should match ONLY the three comment lines that state the rule

# 2. the values — every token in every accent x theme combination, checked
#    for a hue in the forbidden 255-345 deg band at any meaningful saturation
```

Last run: **48 tokens checked across 3 accents x 2 themes, 0 in the forbidden
band.** Platinum lands at hue 207 / saturation 0.08 — a cool grey, not a blue
and nowhere near violet; bronze at hue 25.

---

## 1. Design direction

"Private bank meets editorial luxury." Posh, calm, expensive. **Not** a
neon-gradient AI dashboard.

- Generous whitespace. Let sections breathe; under-fill rather than over-fill.
- Hairline **1px** borders, never 2px or heavier for structure.
- Soft **layered** shadows (`shadow-soft`, `shadow-lifted`, `shadow-overlay`),
  warm-tinted, never coloured. Each is ambient fill + key light + a long
  ambient throw; `shadow-soft-lift` adds the top-edge highlight as an inset.
- Subtle paper-grain texture, applied once via `.paper-grain` on the shell.
- **Glass blur only on overlays** — the top bar, popovers, drawers, scrims, the
  palette, the floating composer, the hero plinth. Never on a content card.
- Status reads through small marks (dots, hairlines, micro labels), not through
  large blocks of colour.

### Two corner radii, and only two

`--r-sm` (3px) for everything structural, `--r-lg` (10px) for the few large
overlays that read as a slab (the shortcuts sheet, the palette). Tailwind's
`rounded-md`/`xl`/`2xl`/`3xl` are **aliased onto that pair** in
`tailwind.config.ts`, so a stray `rounded-xl` cannot introduce a third.
`rounded-full` stays, but only for genuine circles — dots, status marks,
scrollbar thumbs — never as a pill on a button or a chip.

Never write `rounded-[3px]`; use `rounded-sm`. An arbitrary radius is a third
radius waiting to drift.

### Rhythm, and the density dial

Every structural vertical measure is a multiple of **4px** and is expressed
through a token, so `comfortable` and `compact` cannot drift apart — compact is
the same composition at `0.78` of the air:

| Token | Tailwind | Comfortable | Use |
| --- | --- | --- | --- |
| `--gap-section` | `space-y-section`, `gap-section` | 72px | between top-level stages |
| `--gap-block` | `space-y-block`, `mt-block` | 48px | between briefing sections |
| `--gap-group` | `mt-group`, `gap-group` | 24px | label to content |
| `--pad-card` | `px-card`, `py-card` | 36px | the lead card's padding |
| `--pad-card-tight` | `p-card-tight` | 20px | a dense card |

`[data-density='compact']` sets `--density: 0.78` and nothing else. If you add
a new structural gap, use a token — a hard-coded `space-y-12` is invisible to
the density dial and will look wrong in compact.

## 2. Typography

| Family | Role |
| --- | --- |
| **Fraunces** (fallback Cormorant Garamond) | headings, the answer narrative, headline figures |
| **Inter Tight** (fallback Manrope) | all UI text, labels, buttons, tables |
| **JetBrains Mono** | SQL, run ids, raw contract values |

Type scale (Tailwind names in `tailwind.config.ts`). **Every line-height is a
multiple of 4px**, so stacked type lands on the baseline grid without
correction:

| Name | Size / line-height | Use |
| --- | --- | --- |
| `display` | 56 / 60, −0.024em | hero headline |
| `figure` | 44 / 48, −0.014em | headline numbers |
| `h1` | 38 / 44, −0.015em | conclusion narrative |
| `h2` | 26 / 32 | section heads |
| `h3` | 18 / 24 (sans, 500) | card titles |
| `body-serif` | 17 / 30 | long-form narrative |
| `body` | 15 / 24 | interface prose |
| `small` | 13 / 20 | metadata |
| `micro` | 11 / 16, 0.08em, uppercase | badges, labels, footer strip |

### Optical sizing

Fraunces carries an `opsz` axis, and using it is the single biggest lever in
the design. Three utilities, declared in `index.css`:

| Class | `opsz` | Use |
| --- | --- | --- |
| `.opsz-display` | 120 | the hero headline, headline figures, pinboard tiles |
| `.opsz-title` | 48 | card titles, section headings, the question |
| `.opsz-text` | 14 | the wordmark and serif copy at body size |

Only `opsz` is named in `font-variation-settings`, deliberately: naming an axis
overrides the property that maps to it, so leaving `wght` out means a
`font-light` display heading stays light. If you add `'wght'` there you will
silently break every weight class on that element.

`index.html` must keep serving the **variable** face
(`Fraunces:opsz,wght@9..144,300..600`) or the axis does nothing.

### Figures

**Data is tabular and lining; narrative is old-style.** Two different jobs:

- `.tnum` (and the base layer's `th`, `td`, `input`, `code`, `pre`) sets
  `tabular-nums lining-nums` — columns must align and digits must be one width.
- `.onum` sets `oldstyle-nums proportional-nums` for figures inside serif
  prose, so they sit *in* the line instead of standing above it like a column
  of data.

Format every number through `src/lib/format.ts` — never a bare `toString()`.

## 3. Motion

**One motion language.** The same easing everywhere, four durations, never
bouncy.

- `ease-editorial` = `cubic-bezier(.22,.61,.36,1)`, also available as `--ease`.
- `duration-hover` (240) for hovers and small state changes, `duration-micro`
  (300), `duration-reveal` (450), `duration-draw` (600).
- For Framer Motion springs use `{ stiffness: 120, damping: 24 }` — critically
  damped. No overshoot, no low-damping spring, no `backOut`.
- **The answer reveal is choreographed**, not fired all at once: one cue per
  element, **95ms apart** (the midpoint of the 80–120ms band), in reading
  order — status and period, then the conclusion, then the figure, then
  everything that supports it. See the `Reveal` component in `Briefing.tsx`,
  which keeps one running cue counter so a section that is not rendered does
  not leave a gap in the choreography.
- Remove any animation that does not communicate something.

**Reduced motion has two sources** and both must be honoured: the OS
`prefers-reduced-motion`, and the Atelier's own motion dial
(`[data-motion='reduced']`). `index.css` neutralises CSS transitions for both;
`useReducedMotion()` reads both — the media query *and* the attribute, via a
`MutationObserver` — and is what Framer Motion and the few components that
choose a different *composition* (the hero grid freezes, `CountUp` prints its
final value, the listening waveform draws flat) must consult.

## 3a. Signature craft

These are the details that make the product feel made rather than assembled.
They are cheap to break and hard to notice breaking, so they are listed here.
**None of them may be deleted** — "subtract" in a craft pass means quieting
what exists, never removing a feature or a signature effect.

| Device | Where | How |
| --- | --- | --- |
| **Technical grid** | hero only | `TechnicalGrid` — two drifting rules (24px and 120px) on independent cycles, radially masked so it has no visible edge. Still in `--c-grid`, so it re-tones with the accent. Frozen under reduced motion. |
| **Glass plinth** | hero ask box | translucent surface + `backdrop-blur-xl` + `.edge-accent`. Its accent border **traces itself** on focus: one SVG rect with `pathLength={1}` whose `strokeDashoffset` animates 1 → 0 over 600ms. |
| **Accent top edge** | the one focal element per screen | `.edge-accent` — a 1px gradient brightest at the centre, lifting to full on hover. See "the accent is jewellery". |
| **Neutral top edge** | every other card | `.edge-light` — the same device in `--c-lift`, the light the room gives every surface. |
| **Cursor sheen** | hero plinth, evidence cards | `.sheen` + `useSheen`, which writes `--mx`/`--my` in one rAF per frame. |
| **Travelling light** | live pipeline | a point of **accent** runs the hairline between a finished stage and the one still running. The connector itself is hairline; the travelling point is the accent, because it is the thing that is moving. |
| **Count-up** | single-value evidence, pinboard tiles | `CountUp`, ease-out quint. See the SAFE-8 note below. A refreshed pin counts in again because its `key` is the measurement timestamp. |
| **Lineage thread** | claim ↔ evidence ↔ query | `LineageProvider`; hovering or focusing any one lights all three. |
| **Struck hallmark** | the Verified seal | an octagonal assay die with a hairline inner ring and the rim text on a `textPath`. The emboss is real light — an inset highlight on the top edge and a contact shadow under — not a bevel filter, so it works in both themes and prints as a line drawing. |
| **Listening waveform** | the mic button | eleven hairline bars in the accent on a fixed, symmetrical cadence. **Not** a visualisation of the audio: the Web Speech API exposes no amplitude, and drawing one would be an invented figure. |
| **Drawn favicon** | the browser tab | generated from the live accent token per run status — a hollow ring while working, a filled mark when answered, a bar when attention is needed, a cut mark on failure. |
| **Hairline illustrations** | empty states | drawn in `EmptyState.tsx` rather than imported, so they inherit the palette through `.hairline-art` and re-tone with the accent. |

Glass blur remains overlay-only: top bar, palette, popovers, drawers, scrims,
toasts, the floating composer, the plinth. Never on a plain content card.

## 3b. The frontend computes nothing (SAFE-8)

The interface displays what the `AnswerEnvelope` contains. It does not derive,
aggregate, re-round or infer a single figure. Every Part A feature was designed
around this rule, and several were made *narrower* because of it.

**Presentation of a stated value is allowed. Producing a new value is not.**

| Surface | What it is allowed to do | Where the line is |
| --- | --- | --- |
| `CountUp` | animates the *presentation* of a value the envelope holds | final frame is that value through `formatNumber`; intermediate frames are `aria-hidden`; the accessible name is the final value from first render |
| `lib/headline.ts` | **locates** the one figure the envelope already states — a one-row/one-column lookup cell, or an anomaly's `actual` | it never sums, averages, takes a maximum or rounds. No headline figure means the caller says so; it does not fall back to something it computed |
| Pinboard | stores the figure an envelope stated, with the time it was taken | Refresh **re-asks the question** through the same transport the ask box uses and replaces the figure with the *new* envelope's own value. It is not a cached formula. A refresh that returns no headline figure keeps the last good value and the tile says when that was |
| Compare | prints each envelope's own values, aligned band by band | **no computed difference** — not a delta, not a ratio, not "7% higher". The alignment is the comparison. The moment the interface subtracts two figures it has produced a number no claim backs |
| `lib/builder.ts` | composes a *question* from a closed vocabulary | three verified patterns only; it touches no figure at all |
| `DataTable` | sorts (reorders) and searches (hides) the rows the envelope carried | no total row, no computed column, no row count of its own. The authoritative count stays the envelope's `row_count`, printed as such, with the visible count beside it only when a filter is on |
| `lib/download.ts` `toCsv` | transcribes the rows, unformatted | a separator or an en-dash for null would corrupt a spreadsheet. Nothing totalled, no column added |
| Run inspector | prints `step_finished.duration_ms` and `.summary` verbatim; lays bars out from `step_started.at` | bar geometry is *layout*. It deliberately shows **no total of its own** — a sum of stage durations would be ours, so the envelope's `run_metrics.latency_ms` is what is printed |
| `followUps.ts` | fills templates from `scope.metric` and `scope.window` only | no number, finding or insight of ours; returns nothing rather than offer a question the backend cannot answer |
| `TrustPanel` | reports only what the envelope evidences | a check means the envelope positively says so; a dash means it does not say, and we show a dash rather than imply a pass |
| `briefingToMarkdown` | transcribes | if a field is absent its section is omitted, never filled in |
| Listening waveform | a fixed decorative cadence | the Speech API gives no amplitude; a drawn "level" would be an invented figure |

The pre-existing exception, unchanged and still the only one:
`PipelineSummaryBar` sums stage durations for its "stage time" label. It was
approved before SAFE-8 was written down. Do not add a second.

## 4. Accessibility

- Accent focus rings, 2px with 2px offset and the small radius, via
  `:focus-visible`. Never remove an outline without replacing it with an
  equally visible one. The caret, text selection and scrollbars are in the
  palette too.
- WCAG AA contrast minimum for all text in both themes **and all three
  accents**. `sage-ink` exists because the axe gate measured `sage` as type at
  3.7:1; do not revert it.
- A control must not dim below AA to express a state. The composer's disabled
  state used `opacity-60`, which took its own key hints under 4.5:1; it now
  reads through the ground and the placeholder, and the hints — meaningless
  while the field is inert — are hidden instead.
- Interactive elements are real `button`/`a`/`input` elements with accessible
  names. Decorative marks get `aria-hidden`.
- **Prefer content-derived accessible names over `aria-label`.** A label that
  restates visible text can only drift from it; where both exist they must
  agree (axe's `label-content-name-mismatch`). The claim superscript is the
  worked example: the `<sup>` is `aria-hidden` and the detail is `sr-only`
  text *inside* the button, so the name is built from the button's own content.
  This is why the briefing toolbar carries text labels beside every icon.
- Any element with its own scrollbar needs `tabIndex={0}` and a label, or a
  keyboard user cannot scroll it. `SqlBlock` takes a `label` prop for exactly
  this reason — a long query scrolls sideways on a narrow screen.
- A button may never nest inside another button. The rail's star is a *sibling*
  of the question button in a flex row, not a child of it.
- `<dt>`/`<dd>` must be direct children of the `<dl>` or of a **single**
  wrapping `<div>`. Decorations go inside the `<dt>`, positioned absolutely —
  not as another nesting level.
- Skeleton loaders are shaped like the content that replaces them, so there is
  **no layout shift**. Skeletons are `aria-hidden`.
- Modal overlays (`Drawer`, the palette, the shortcuts sheet) move focus in on
  open, trap Tab, restore focus on close, and close on Escape and on the scrim.

### The keyboard

`src/lib/shortcuts.ts` is the **single source of truth**, and the shortcuts
sheet is rendered *from* it — so the sheet cannot drift out of step with the
handlers. Add a binding there and in `App.tsx` together.

| Key | Action |
| --- | --- |
| `Ctrl/Cmd+K` | command palette — the one entry point for asking and for every action |
| `Enter` / `Shift+Enter` | ask / newline |
| `N` | new question |
| `J` / `K` | next / previous question in the rail |
| `B` | pinboard |
| `S` | star this answer |
| `Shift+P` | pin the headline figure |
| `C` | copy the run's SQL |
| `I` | run inspector |
| `P` | presentation mode |
| `?` | shortcuts sheet |
| `Esc` | close any overlay |

Three rules the bindings all obey: inert **while typing**, inert with **any
modifier held**, and inert **while an overlay owns the screen** (`App.tsx`
threads one `bare` flag into every `useHotkey`). Shift is matched exactly for
letters — `S` and `⇧P` never fire for each other — but left unchecked for
symbol keys, where the layout decides whether Shift produces `?` at all.

One consequence worth knowing: submitting from the docked composer leaves focus
in the textarea, so single-letter shortcuts do nothing until focus leaves the
field. That is the "inert while typing" rule working as designed; the toolbar
buttons remain available.

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

The app has **three views**, switched in the left rail (and from the palette's
"Go to" group): **Ask**, **Pinboard**, **Compare**. `App.tsx` holds that state
and every submit path funnels through its one `submit()`, which also returns
the reader to Ask.

| Surface | File | Note |
| --- | --- | --- |
| Command palette | `components/palette/CommandPalette.tsx` | Ask, go to a view, reopen a past answer, and the few actions worth a keystroke. Substring matching over a short curated list — not fuzzy, because predictability is what makes a palette feel fast. **Free text is always offered first**, so Enter on a typed word asks it as a question rather than navigating. |
| How this was computed | `components/queries/QueryList.tsx` | The SQL is a first-class section directly under the conclusion, **expanded by default** — the product's whole promise is that you can check the arithmetic. Line-numbered gutter, hand-rolled highlighter (every library ships a purple theme), copy with a drawn-on tick. |
| Lineage | `components/briefing/LineageContext.tsx` | Derived strictly from `claim.source.id` and `evidence[].source_claims`. It never invents a relationship the backend did not assert. |
| Hero figures | `lib/evidenceTitle.ts` | A lookup returning exactly one row and one column is a headline number, not a table. Titles come from `scope`, never from reading the data — and a comparative run's two identical titles are disambiguated by position, because `scope` only carries the current window. |
| Follow-ups | `lib/followUps.ts` | See SAFE-8. Governed metrics only, window must include the year. Shares its vocabulary with the builder via `lib/metrics.ts`. |
| Export | `lib/exportBriefing.ts`, `lib/download.ts`, print block in `index.css` | "Copy briefing" is Markdown; "Download PDF" is the browser's own print dialogue against the print stylesheet — the most reliable PDF route, no library, no sandbox exception. `data-print="hide" / "show" / "flow"` control what the printed report does. |
| Presentation mode | `components/PresentationMode.tsx` | Renders the **same** `Briefing` with `presenting`, so there is exactly one place the answer is designed. |

### Part A — the power features

| Feature | Files | What to know |
| --- | --- | --- |
| **Pinboard** | `lib/pins.ts`, `hooks/usePins.ts`, `components/pinboard/` | A pin stores the figure, not a formula. Refresh re-asks live; see SAFE-8. Reordering is native HTML5 drag **plus** arrow buttons on every tile, because a drag-only affordance is unreachable without a pointer. Capped at 24 pins. |
| **Compare** | `components/compare/CompareView.tsx` | Two stored answers, aligned in five bands. Computes no difference — that restraint is the feature. Needs two stored envelopes; shows a designed empty state below that. |
| **Guided builder** | `lib/builder.ts`, `lib/metrics.ts`, `components/ask/QuestionBuilder.tsx` | Three pickers → one of three verified question patterns, with a live preview of the sentence. **There is deliberately no dimensional breakdown**: a question naming a dimension routes to `driver`, which raises (gap 14), so the panel states the absence rather than offering a picker that can only fail. |
| **Voice input** | `hooks/useSpeech.ts`, `components/ask/VoiceButton.tsx` | Real feature detection; the mic is **not rendered at all** where there is no engine. No polyfill — a button that cannot work should not be on screen. |
| **Result tables** | `components/evidence/DataTable.tsx` | One component backs both lookup results and the charts' "view as table". Sort, search, Export CSV. Numeric columns are detected **from the data**, not the declared type (gap 15). |
| **Charts** | `components/evidence/ChartFrame.tsx`, `EvidenceTables.tsx` | "View as table" and "Download PNG". Both views stay mounted so toggling never re-animates the chart; the hidden one is taken out of the a11y tree with `hidden`. PNG is 2× on the page's own ground — a transparent PNG would be unreadable. |
| **Run inspector** | `components/inspector/RunInspector.tsx` | Waterfall from the SSE events; raw envelope with copy. Lays out from real `step_started.at` timestamps when every stage has one, and falls back to butting stages up in order when a reconnect replayed only `step_finished`. |
| **History, stars, filters** | `lib/historyStore.ts`, `hooks/useSession.ts`, `components/shell/LeftRail.tsx` | Persists to localStorage **with a validator** — stored envelopes come from an older build of this app, so they are as untrustworthy as anything off the wire. An entry that fails validation keeps its question and drops its envelope. 40 entries max; in-flight runs are dropped on write. Filters and search appear once there are 3+ questions. |
| **Keyboard + shortcuts sheet** | `lib/shortcuts.ts`, `components/help/ShortcutsSheet.tsx` | See §4. |
| **Theme Atelier** | `lib/settings.ts`, `hooks/useSettings.ts`, `components/settings/SettingsPopover.tsx` | Accent, density, motion, stamped as `data-*` on `<html>` — nothing threaded through React. Also holds "replay the tour" and "forget stored history". |
| **First-run tour** | `lib/tour.ts`, `components/tour/Tour.tsx` | Four steps, once, skippable, replayable. Targets are named by `data-tour` attribute; a step whose target is **not on the page is skipped, not pointed at nothing** — on a first run there is no pipeline or lineage yet. `?tour=1` forces it. One SVG plane with a masked hole, not four panels that have to meet at the corners. |
| **Toasts** | `components/ui/Toast.tsx` | `done` / `note` / `fault`. Never a dialogue, never an action, never more than three deep. Polite live region; `assertive` only when something failed. |
| **Tab status** | `hooks/useDocumentStatus.ts` | Title per phase, favicon drawn per status from the live accent token. |

### Local persistence

Everything the product remembers is remembered **in this browser**, and every
surface that reads it says so. `lib/storage.ts` is the only module that touches
`localStorage`; every accessor is total, so a private window, blocked site data
or a quota failure all return the fallback instead of throwing.

| Key | Holds |
| --- | --- |
| `ds-agent-theme` | light / dark / system |
| `ds-agent-accent`, `-density`, `-motion` | the Atelier |
| `ds-agent-history` | up to 40 questions with their envelopes and stars |
| `ds-agent-pins` | up to 24 pinned figures |
| `ds-agent-tour-seen` | whether the tour has run |

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

Four gates. The first two must be clean before any commit; the last two before
any PR. The accessibility gate is not optional — the colour and contrast tokens
were set *from* its measurements.

```bash
npm run typecheck        # strict; must stay clean
npm run build            # must stay clean, no warnings

# the colour rule, mechanically — names AND values (see section 0)
grep -rniE "purple|violet|lavender|indigo|magenta|pink|fuchsia" src/

# the browser gates, with the dev server running
npm run verify:features  # 9 mock states + ~34 feature assertions + axe
npm run verify:live      # the 4 verified chips against the REAL backend
npm run audit            # screenshots + axe across 17 scenes x 2 themes x 2 widths
```

There is **no linter configured** — no ESLint, Biome or oxlint dependency or
config. Do not add one as a side effect of another change.

Backend, from the repo root: `python -m pytest backend/tests -q`.

### Last full verification

| Gate | Result |
| --- | --- |
| `pytest backend/tests` | **232 passed** (1 pre-existing third-party `StarletteDeprecationWarning` from `fastapi/testclient`) |
| `npm run typecheck` | clean from a wiped `tsbuildinfo` |
| `npm run build` | clean, no warnings. `index` 359 kB / 105 kB gzip; `AnomalyChart` lazy 425/115; `motion` 122/41; `DriverBars` lazy 4/1.5; CSS 55/10.5. Recharts stays out of the initial load |
| colour names | only the three comment lines that state the rule |
| colour values | 48 tokens x 3 accents x 2 themes, **0** in the forbidden hue band |
| live, 4 chips | **10/10** — each reaches `answered` with conclusion, evidence, SQL, claims, Verified 4 of 4, on four distinct run ids |
| mock, 9 states | **10/10**, 0 console errors |
| feature smoke | **44/44** |
| axe, hero + answer, both themes | **0 violations**, including `minor` and `best-practice` |

### Writing a browser gate

Five things the harnesses learned the hard way, all commented in the scripts:

- Under `?mock=1` the MockBar puts **every status word on screen** before a
  question is asked, so waiting for "BLOCKED" or "REFUSED" to detect a settled
  run returns instantly. The settle signal is the pipeline summary bar, which
  only renders once the run is out of flight **and** the envelope is collected.
- `SectionLabel` uppercases through **CSS**, so `innerText` comes back
  uppercased. A case-sensitive text assertion tests the stylesheet, not the
  content.
- Submitting from the composer leaves focus in the textarea, where
  single-letter shortcuts are correctly inert, so a keyboard assertion must
  blur first.
- A page carries **several `DataTable`s** — a lookup's result rows and every
  chart's "view as table", which `ChartFrame` keeps mounted so toggling never
  re-animates the chart. An unscoped `tbody tr` therefore reads two row sets
  concatenated, and no column is monotonic across the join. `LookupTable`
  stamps `data-testid="lookup-table"` so a harness can name the one it means.
- The app **restores the last briefing from `localStorage`** on load, seal and
  all, so reusing one browser context across checks means a wait for "the seal
  is present" returns against the *previous* run. `verify-live` takes a fresh
  context per chip and additionally requires the run id in the top bar to be
  one it has not already asserted.

And one that is not a bug: `GET /api/runs/__probe__` returns **404 by design**
— there is no `/api/health`, so a 404 *is* the liveness signal (gap 12).
Chromium logs every 404 resource as a console error, so a console-error gate
must count that one separately or it is permanently red for a success.

## 9. Commands

```bash
cd frontend/web
npm install
npm run dev              # http://localhost:5173, proxies /api to 127.0.0.1:8000
npm run typecheck        # strict, must stay clean
npm run build

# browser gates — all three need the dev server up
npm run verify:features  # mock states, features, axe   (no backend needed)
npm run verify:live      # the 4 chips                   (needs the backend)
npm run audit            # screenshots + axe; writes scripts/shots/ (git-ignored)
```

Useful URLs: `?mock=1` for every designed state without a backend, `?tour=1` to
force the first-run tour.

Backend, from the repo root:

```bash
.venv/Scripts/python.exe -m uvicorn app:app --app-dir backend/src --port 8000
.venv/Scripts/python.exe -m pytest backend/tests -q
```

## 10. Track 5 — the V2 answer (added; nothing above is superseded)

The app now asks through **`POST /api/v2/ask`** and collects from
**`GET /api/v2/runs/{id}`** (whose envelope is a superset of V1's), falling back
to `/api/ask` for good if the backend has no V2 route. A `contract_version:
"1.0.0"` envelope still renders exactly as before: every V2 surface checks
`asV2()` (`lib/v2.ts`) first and renders nothing without it.

### SSE on a V2 run

A V2 run emits the **same five V1 events, unchanged**, plus these progress
events from `backend/src/pipeline_v2.py` / `executor_v2.py`, which `lib/sse.ts`
now listens for: `context`, `intent`, `grounding`, `plan`,
`plan_step_started`, `plan_step_finished`, `engine_running`, `compose`,
`replan`. The V2 `clarify` event also carries `question`, `options`, `round`
and `default_option_id`. Types live in `src/types/v2.ts`. The seven-stage track
is unchanged; the plan is a separate checklist.

### Surfaces

| Item | Files | Note |
| --- | --- | --- |
| Generic chart renderer | `components/viz/VizFrame.tsx` (lazy), `VizCard`, `VizGallery`, `lib/vizData.ts` | Draws any `VisualizationSpec` by `kind`/`encoding`; "view as table" through the shared `ChartFrame` + `DataTable`. Data is resolved from the envelope: `source_query_id` → the lookup block; `source_artifact_id` = `"<step>:<tool>#<path>"` → that step's engine block, then a dotted path. |
| Plan checklist | `components/briefing/PlanView.tsx` | Type badge per step (SQL / Analytical table / Python · forecast / Python · diagnostic …). Only the running step wears the accent. "Running model — this can take ~N s" uses `TYPICAL_MODEL_SECONDS`, interface copy that is never shown beside a data figure. |
| Conversation | `components/thread/*`, `InterpretedAs.tsx` | Chat-style earlier turns, the backend's rewritten question as an "interpreted as" chip, **New topic** (sends `reset_context` and calls `/api/sessions/{id}/reset`), and **replay** of stored conversations turn by turn. History entries gained an optional `threadId`. |
| Clarification | `components/ask/ClarifyOptions.tsx` | Option chips (send `option_id`), "Round n of 2", the default and its rationale; the free-text box stays. |
| Intent layouts | `components/briefing/IntentPanels.tsx`, `FitQuality.tsx` | WHY: ranked drivers in engine order + waterfall + causal boundary. FORECAST: fan + method/fallback + the MAPE **ledger claim** verbatim ("not backtested" when absent, never 0) + trend/seasonality on request. WHAT IF: scenario charts + engine assumptions and disclosures. NOW WHAT: `next_actions` via the existing `NextActions`. DISCOVERY: the catalog's claims + its "Try: …" example questions. |
| Also | `AssumptionsPanel`, `SyntheticBadge`, `FollowUpChips` | Backend `follow_ups` verbatim (none → nothing); V1 envelopes keep `lib/followUps.ts`. |
| Feedback | `components/briefing/FeedbackBar.tsx`, `hooks/useFeedback.ts`, `lib/feedback.ts` | Thumbs + optional reason per answer; `ds-agent-feedback` locally, and `POST /api/sessions/{id}/feedback` live. |

### SAFE-8 notes for the new code

- A waterfall is drawn as **contributions from zero** (sage up, terracotta
  down), never as running totals — a running total would be our figure.
- Several series share an axis by *moving* cells into one object per x value;
  nothing is summed, sorted, sliced or binned. Top-N is the backend's
  (`encoding.limit`, remainder in the caption).
- Axis extents including zero (`zero_baseline`) are layout, like bar geometry.
- A V2 lookup block (string columns, no `row_count`) is reshaped in
  `asLookup`, never re-counted: `row_count` is `null` and the table prints none.

### Mock mode

`lib/mock/v2.ts` + `v2Scenarios.json`: 16 envelopes **with their event
streams captured from the real V2 pipeline** on the backend's synthetic test
fixture (so their figures are the fixture's), loaded on demand. The MockBar
lists them under "V2 · every intent"; `Summarize revenue` walks the clarify flow
(free text → round 2; an option → answered). Every V1 mock question routes as
before.

### Last verification (Track 5)

| Gate | Result |
| --- | --- |
| `pytest backend/tests` | 1058 passed, 49 skipped (Olist file absent), 0 failed |
| `npm run typecheck` / `npm run build` | clean from a wiped cache, no warnings; Recharts and the V2 mock JSON stay lazy |
| colour names / values | only the three rule comments / 125 token values, 0 in the forbidden band; no raw colour in new code |
| `verify:features` | **67/67** — the original 44 plus 23 V2 checks, incl. axe with `minor` + `best-practice` on the new surfaces in both themes |
| `verify:live` | 10/10 against the backend on the synthetic fixture (the Olist snapshot was not available) |
