# V2 demo script

A 15-20 minute walk through the six business questions - what, why, so what, what
next, what if, now what - plus discovery, a conversation and a clarification.
**Every step below passed live execution** through `POST /api/v2/ask` on
2026-10-31, replayed by [`scripts/verify_demo.py`](../scripts/verify_demo.py) from
[`scripts/demo_v2.yaml`](../scripts/demo_v2.yaml). Re-run it before every demo; it
fails if any step, or any hero chip, does not pass.

```bash
python scripts/verify_demo.py --serve          # 18/18 steps must pass
```

## What was verified, and on which data

| Database | Result | Use it to |
| --- | --- | --- |
| `data/brazil_ecommerce_v2.sqlite` built with `--fixture` (4,975 orders, Olist-shaped, seeded) | **18/18 steps passed** | rehearse; every figure quoted below comes from this build |
| Real-scale stand-in: the same generator at the real catalogue size (32,951 products, 99,500 orders, 187,220 price changes), scratch only | **18/18 steps passed** | check nothing times out at real volume |
| The real Olist snapshot `brazil_ecommerce.sqlite` | **not verified** - not available in this environment | - |

The figures in this script are **fixture figures, not Olist results**; on the real
snapshot every number will differ. What carries over is the shape of each answer.
Synthetic tables (marketing, traffic, stock, prices, promotions, delivery SLAs,
segments, targets) are generated for demonstration and every answer that reads one
says so.

**Not verified: the in-browser click-through.** The automated browser gates
(`npm run verify:features`, `npm run verify:live`) and a click-through of the hero
chips could not run here: the project's Playwright (1.64.1) expects Chromium revision
1248 and the environment provides 1243. The demo was verified at the API level - the
same requests the UI sends - and the frontend type-checks and builds cleanly.
Click through the chips once on your machine before presenting.

## Setup

On Windows, follow [`RUN_LOCALLY.md`](RUN_LOCALLY.md) step by step (Command Prompt + VS Code);
`python scripts/check_setup.py` must print `OK` before you start the backend. In short:

```bash
python scripts/build_v2.py --source brazil_ecommerce.sqlite   # or --fixture without the snapshot
export DS_AGENT_DB=data/brazil_ecommerce_v2.sqlite             # REQUIRED - see "If 'what if' says insufficient evidence"
export DS_AGENT_TOKEN=<a random token of 32+ characters>
uvicorn app:app --app-dir backend/src --port 8000
cd frontend/web && npm run dev                                  # http://localhost:5173, same DS_AGENT_TOKEN
```

Ollama is optional: every step answers with the deterministic fallbacks (verified
with Ollama off). Start a **New topic** before each scene so a follow-up never picks
up the previous scene's context.

### If "What if we raise prices 5%?" says INSUFFICIENT EVIDENCE

Two causes were found and handled:

1. **Real-catalogue scale (fixed).** At 32,951 products the price panel took ~80 s,
   the plan's 60 s budget skipped the baseline step, and the scenario returned
   insufficient evidence without ever fitting. `prep.daily_list_price` is now
   vectorised (81 s -> 0.35 s, identical output), and the question answers in about
   1.5 s at that scale.
2. **No synthetic tables (by design).** If the backend is not pointed at the V2
   build (`DS_AGENT_DB` unset, so it serves the plain snapshot), there is no price
   history to fit an elasticity on, and it still - correctly - refuses to invent one.
   The message now says exactly that and how to build the tables, instead of
   "only price-change scenarios have a fitted response".

The price question was **kept, not substituted**: the elasticity fits reliably on
both builds and its interval contains the planted true value (-1.5) on both.

## The hero chips

The chips under the ask box are the demo's single-question beats, WHY first (an
existing UI gate requires the first two to be WHY questions). They are defined in
`SuggestionChips.tsx`, and `verify_demo.py` fails if they differ from `hero_chips`
in `demo_v2.yaml` - so a chip is always a question that has just passed.

| # | Chip | Scene |
| --- | --- | --- |
| 1 | Why did revenue drop in the top category in April 2018? | 3 |
| 2 | Why did order count fall in December 2017? | 4 |
| 3 | Did the carrier cause the delivery delays? | 6 |
| 4 | How far are we off the regional targets? | 5 |
| 5 | Forecast revenue for the next 3 months | 7 |
| 6 | What if we raise prices 5%? | 8 |
| 7 | Which customer segment should we target? | 9 |
| 8 | How does revenue trend look today and what will it be in 3 months? | 10 |
| 9 | What data do you have? | 1 |
| 10 | How many orders were there in August 2018? | 2 |
| 11 | How did revenue in 2018 compare to 2017? | 14 |
| 12 | Was order count unusual in August 2018? | 13 |

**Substitutions** (each replaced question still exists and was checked; it was taken
off the chips because its live answer was a poor demo beat, not because it errors):

| Was a chip | Now | Why |
| --- | --- | --- |
| How much did the April 2018 drop cost us? | How far are we off the regional targets? | Answers, but on this data April is *above* its expected value, so the "cost" comes out as a positive gap - honest, and confusing on stage. |
| Why did revenue spike in May 2018? | Why did order count fall in December 2017? | Not in the evaluation bank, and its answer names no driver. The replacement is evaluated (G3) and recovers the planted stockouts. |

In mock mode (`?mock=1`) the three new chips have no captured V2 mock, so they show
an existing designed state (driver or clarify); mock fixtures were not changed.

## The script

Latency is the client wall clock per request on this container: fixture / real-scale stand-in.

### 1. Discovery - "What data do you have?" (37 / 100 ms)

Point at: 24 tables grouped real vs. synthetic, row counts and date spans, every
synthetic table labelled. Say: *the agent starts by telling you what it can and
cannot see - nothing below is answered from data it hasn't listed.*

### 2. WHAT - "How many orders were there in August 2018?" (25 / 35 ms)

> Order count for 2018-08 was 326.

Point at: the SQL under the answer, expanded by default. Say: *governed metric,
compiled SQL, read-only, and the number is a ledger claim linked to that query.*

### 3. WHY - "Why did revenue drop in the top category in April 2018?" (278 / 302 ms)

Point at, in order: the restated question (revenue cannot be split by category, so
GMV is used, and the answer says so); the drop against the month before (R$ -3,552.94)
decomposed by category; then the window screen - *paid search spend was 35% below
its trailing median in the window, an unusual level for it (robust z -5.8); the
timing is consistent with the change and is not evidence of a cause.* That is the
planted marketing cut (E1). Note the anomaly line: April was 45.7% above its
*expected* value but below March - both are true and both are on screen.

### 4. WHY - "Why did order count fall in December 2017?" (482 / 467 ms)

> The total change in order count was -93 ... In the window, stockout rate was
> 654.1% against its trailing median ... (robust z 9.2)

The planted stockouts (E2), found in the same window as the Black-Friday peak that
the baseline does not mistake for the cause.

### 5. SO WHAT - "How far are we off the regional targets?" (27 / 31 ms)

> The gap to target is R$ -2,598.3 (94% attainment).

Sized by the impact engine against the (synthetic) regional targets.

### 6. WHY with a control group - "Did the carrier cause the delivery delays?" (1.4 / 1.3 s)

Point at: jadlog's share of the SLA-breach change, then *a difference-in-differences
effect of 0.54 delay days, specific to that group against the comparison group
(evidence grade 3)*. Say: *grade 3 means specific to the carrier - still not "caused";
the causal-boundary note is on the answer.* The planted delay spike (E4).

### 7. WHAT NEXT - "Forecast revenue for the next 3 months" (15 / 15 ms)

> Anchored on 2018-08, the last complete month, the revenue forecast for 2018-09 to
> 2018-11 ends at R$ 46,314.51 ... interval of R$ 33,931.25 to R$ 58,697.77 (ets
> model). Month by month ... backtest MAPE 28.7%.

Point at: the anchor (the truncated 2018-09/10 months are never fitted on), the fan
chart, the method actually used (ETS: Prophet is not installed) and its backtest.

### 8. WHAT IF - "What if we raise prices 5%?" (287 ms / 1.2 s)

> For a price change of 5%, the fitted elasticity is -1.61 (interval -2.25 to -0.97).
> Demand changes by -7.6% and revenue by -2.9% (Monte Carlo interval -5.9% to 0.1%)
> ... This is an observational estimate on synthetic data, not the result of a price
> experiment.

At real scale: -1.64 (interval -1.83 to -1.45). The planted elasticity is -1.5; both
intervals contain it. Say: *the coefficient is fitted, never assumed; no fit, no number.*

### 9. NOW WHAT - "Which customer segment should we target?" (318 ms / **~5 s**)

Point at: three ranked options with assumptions, trade-offs, what to monitor and what
data would change the ranking. Options cite segments by rank; every figure stays in
the claims. **At real scale this takes ~5 s** (it was ~9 s before the clustering loop was
vectorised) - start talking before you click.

### 10. Two intents at once - "How does revenue trend look today and what will it be in 3 months?" (838 / 804 ms)

> Revenue for 2017-09 to 2018-08 was R$ 471,889.8 ... the revenue forecast for 3
> periods ahead ends at R$ 47,652.59 ...

One run, one envelope, both halves answered (the plan lists a step per intent).

### 11. A conversation (New topic first)

| Turn | Ask | Shows |
| --- | --- | --- |
| 1 | What was revenue in 2018? | R$ 335,452.41 for 2018-01 to 2018-08 (clipped to the last complete month, said so) |
| 2 | What about SP? | R$ 140,436.08 - the "interpreted as" chip shows what was carried over |
| 3 | And RJ? | R$ 43,500.06 - inherits from turn 2, not turn 1 |
| 4 | Forecast that | RJ revenue forecast, anchored on 2018-08, RJ filter kept |

### 12. Clarification (New topic first)

"How are sales doing?" asks one question - which metric - with options and a stated
default. Choose the default: it answers revenue over the last 12 complete months
(R$ 471,889.8) and records the default it applied, without asking a second question.

### 13-14. V1 still works

"Was order count unusual in August 2018?" (326 against an expected 325.5 - within
normal range) and "How did revenue in 2018 compare to 2017?" (R$ 335,452.41, +136.7%
against the aligned 2017-01 to 2017-08 window).

## Do not ask in the demo

These fail or answer poorly in the current evaluation ([`EVAL_V2.md`](EVAL_V2.md)):

| Question | What happens |
| --- | --- |
| What if credit card share grew to 85%? / restored the marketing spend we cut? / eliminated the stockouts? | `insufficient_evidence` - no fitted relationship; the agent declines rather than invent one |
| Do you have customer age or gender? / What if we launched in Argentina? | a clarification naming the missing attribute, where the spec expects a refusal |
| GMV in 2018, then "And last year?" | resolves to Jan-Aug 2017 (aligned) without saying so |
| What is SP worth to us? | answers, but with a change against a baseline rather than SP's share |
| Why is RJ lower? (after the conversation) | answers the total change across states, not the RJ comparison |
| What are the stockouts costing us? | `insufficient_evidence` at real scale (zero baseline) |
