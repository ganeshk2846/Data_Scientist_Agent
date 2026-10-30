# V2 Scope — Question Taxonomy

**Location in repo:** `spec/v2/scope.md`
**Status:** proposal for review. Nothing in this file changes V1 behaviour.
**Governing specs:** [`requirements.md`](../requirements.md), [`Interfaces.md`](../Interfaces.md), [`DESIGN_DETAIL.md`](../../docs/DESIGN_DETAIL.md)
**Companions:** [`contracts.md`](contracts.md), [`build-plan-v2.md`](build-plan-v2.md)

---

## 0. Why V2 exists

Reviewers found that the agent answers **"what"** and little else. That is an
accurate reading of the code, not a misunderstanding:

| Evidence in V1 | Consequence |
| --- | --- |
| `RouteLabel = lookup \| anomaly \| driver \| risk \| clarify \| refused \| blocked` (`contracts/models.py:497`) | There is no route that can carry *impact*, *forecast*, *scenario*, *prescriptive* or *discovery*. |
| `risk` returns `insufficient_evidence` unconditionally (`orchestrator.py:143-163`) | The one forward-looking route is a stub. |
| `next_actions=()` hardcoded (`service.py:646`) | "Now what" is structurally absent from every answer. |
| `_contribution_table(current_execution, comparison_execution, …, current=…, comparison=…)` (`orchestrator.py:518`) passes `current` twice | **The driver route raises `TypeError` on every call.** "Why" is unreachable live, which is why reviewers only ever saw "what". |
| `session_id` is stored and never read (`service.py:147`, `331`) | No conversation context, so no follow-ups. |
| `clarification_of` is ownership-checked only (`service.py:322-325`) | A clarification reply is treated as a brand-new question. |
| `Orchestrator.run` is a flat `if route == …` chain (`orchestrator.py:166-213`) | No multi-step planning; one route does one thing. |
| `AnalystHarness` registers `anomaly` and `driver` only (`harness.py:45-49`) | No Python engine for forecast, scenario or impact. |
| `AnswerEnvelope` carries no visualization field | Charts are inferred by the frontend from evidence shape (`frontend/web/CLAUDE.md` gap 3). |

V2 adds the missing question classes **without weakening the safety boundary**.
The invariant is unchanged and non-negotiable:

> **SAFE-8.** A language model may choose, draft and explain; it never computes a
> number. Every number in an answer comes from SQL executed through the
> read-only gateway or from a registered Python engine, and is linked to an
> evidence claim.

A forecast is a number. A scenario output is a number. An elasticity is a
number. Therefore **every** V2 intent that produces a figure routes it through a
registered engine with a typed contract, tests and planted-truth scoring — never
through model prose. The LLM's enlarged job in V2 is *understanding and
planning*, not arithmetic.

### 0.1 The answering posture — V2's second principle

SAFE-8 is about *where numbers come from*. It is not a licence to refuse. V1
over-corrected: fail-closed became fail-silent, and a reviewer asking an
ordinary business question got a clarification.

> **V2-ANS-1.** Prefer **answering with clearly stated assumptions** over
> refusing. Refuse only when an input genuinely does not exist in the
> warehouse — not when it is merely uncertain, thin, or needs a default.

The two principles compose: an assumption is stated in prose and recorded in
`assumptions`; a *number* still comes from an engine. An engine that fits on
thin history answers and says the interval is wide; it does not refuse because
the interval is wide. `ABS-3` (over-refusal must be reported) is promoted in V2
from a metric to a gate — see §9, the must-answer set.

---

## 1. The six business questions, and the eight intents that serve them

| Business question | Reviewer's phrasing | Intent(s) | Produces numbers via |
| --- | --- | --- | --- |
| What happened? | **What** | `descriptive` | `sql` |
| Why did it happen? | **Why** | `diagnostic` | `sql` + `python.driver`, `python.anomaly` |
| Does it matter? | **So what** | `impact` | `sql` + `python.impact` |
| What happens next? | **What next** | `forecast` | `sql` + `python.forecast` |
| What if we change something? | **What if** | `scenario` | `python.scenario` (over a fitted engine) |
| What should we do? | **Now what** | `prescriptive` | ranking over *already quantified* engine outputs |
| What data do you even have? | — | `discovery` | `catalog` (no figures, or governed counts only) |
| What exactly do you mean? | — | `clarify` | no tool calls at all |

`discovery` and `clarify` are first-class intents, not error states. V1 treats
"I don't understand" as a failure (`status: "clarify"`); V2 treats it as a turn
in a conversation that carries forward.

### 1.1 Intent definitions

| Intent | Definition | Terminal? | Max engine calls |
| --- | --- | --- | --- |
| `discovery` | Asks what the warehouse contains — tables, metrics, dimensions, coverage, grain, freshness. Answered from the catalog and metric registry. | yes | 0 |
| `clarify` | The question cannot be resolved to a metric + window + grain without a choice the user must make. | no — expects a reply | 0 |
| `descriptive` | Reports a measured value, a breakdown, or a period-over-period comparison. | yes | 0 (SQL only) |
| `diagnostic` | Asks whether a change is unusual and what moved with it. | yes | `anomaly`, `driver` |
| `impact` | Quantifies what a change is worth — revenue at stake, share of total, exposure of a segment. | yes | `impact` |
| `forecast` | Projects a governed metric forward with an interval. | yes | `forecast` |
| `scenario` | Re-runs a fitted relationship under a stated change to an input. | yes | `scenario` (requires a prior `forecast` or `impact` fit) |
| `prescriptive` | Ranks 2–3 actions against quantified impact, evidence grade and feasibility. | yes | 0 — ranks existing outputs (`REC-2`) |

### 1.2 Routing rules that survive from V1

- A question below the confidence threshold becomes `clarify`, never a guess
  (`RTE-3`, `ABS-4`).
- A metric, dimension or attribute outside the catalog becomes a refusal naming
  the missing attribute (`ABS-1`, `SAFE-6`).
- `scenario` without a fitted engine upstream is `insufficient_evidence`, not an
  invented sensitivity.
- `prescriptive` with every upstream evidence grade below 2 returns the cheapest
  information-gathering step (`REC-4`), not an intervention.

---

## 2. The data these questions are grounded in

V2 runs against **two layers**: the real Olist snapshot (unchanged, read-only)
and a seeded synthetic layer that extends it to 18+ tables. Examples below are
marked **[R]** real, **[S]** synthetic, or **[R+S]** where the answer joins both.

### 2.0 Layer 1 — the real snapshot [R]

Verified by direct query on `brazil_ecommerce.sqlite`. **Never modified.**

**Snapshot:** Olist Brazilian e-commerce, 9 tables.

| Table | Rows |
| --- | --- |
| `orders` | 99,441 |
| `order_items` | 112,650 |
| `order_payments` | 103,886 |
| `order_reviews` | 99,224 |
| `customers` | 99,441 |
| `products` | 32,951 |
| `sellers` | 3,095 |
| `geolocation` | 1,000,163 |
| `product_category_translation` | 71 |

**Governed metrics** (`catalog/registry.py`, 9 entries): `gmv`, `revenue`,
`order_count`, `aov`, `review_score`, `freight_value`, `item_count`,
`customer_count`, `cancellation_rate`.

**Governed dimensions:** `customer_state` (27 values; SP 41,746 · RJ 12,852 ·
MG 11,635), `customer_city`, `seller_state`, `order_status` (8 values;
`delivered` 96,478 · `canceled` 625), `product_category` (71 English names),
`payment_type` (`credit_card` 76,795 · `boleto` 19,784 · `voucher` 5,775 ·
`debit_card` 1,529 · `not_defined` 3), `month`, `year`.

### 2.1 The truncation trap — mandatory for every forecast and scenario example

`order_purchase_timestamp` spans **2016-09-04 → 2018-10-17**, but the tail is
not real volume:

| Month | Orders |
| --- | --- |
| 2018-08 | 6,512 |
| 2018-09 | **16** |
| 2018-10 | **4** |

**The last complete month is 2018-08.** Months 2018-09 and 2018-10 are
truncated collection artefacts, as is 2016-09 at the head. Any engine that fits
on them will produce a catastrophic false trend, and any answer that reports
"September 2018 revenue" as a fact is reporting an artefact as a finding.

Therefore, normatively:

- **V2-DATA-1.** The semantic layer MUST publish `last_complete_period` per
  metric and grain, computed from a completeness rule, not from `max(date)`.
- **V2-DATA-2.** `python.forecast` MUST refuse to fit across a period flagged
  incomplete, and MUST state its anchor period in its output.
- **V2-DATA-3.** A `descriptive` answer whose window includes an incomplete
  period MUST carry a visible caveat naming the period and its coverage.

This already shows up in the product: the frontend's live suggestion chip was
tuned to May 2018 "for complete consecutive history baseline"
(commit `6348abb`). V2 makes that a contract instead of a chip choice.

The synthetic layer (§2.2) is generated **only** for complete periods
2016-10 → 2018-08, so it never reintroduces the trap it was built around.

### 2.2 Layer 2 — the synthetic layer [S]

The real snapshot cannot answer "why" questions properly: it has no marketing
spend, no stockouts, no prices over time, no promotions, no traffic. Attribution
over `product_category` alone is the only "driver" available, which is why V1's
diagnostic ceiling is so low. The synthetic layer supplies the **operational
indicators** that `DRV-5` already requires and the data that makes `impact`,
`scenario` and `prescriptive` answerable rather than refusable.

**Hard rules.**

- **V2-SYN-1.** `brazil_ecommerce.sqlite` is **never modified**. The generator
  writes `data/brazil_ecommerce_v2.sqlite`, which contains the real tables
  copied verbatim plus the synthetic tables.
- **V2-SYN-2.** Generation is **seeded and deterministic**: same seed ⇒
  byte-identical database. `scripts/synth/generate.py`, numpy + pandas (SDV and
  Mimesis optional, behind an extra).
- **V2-SYN-3.** Every synthetic table is **keyed to real Olist values** — real
  `order_id`, `product_id`, `seller_id`, `customer_state`, the 71 real
  categories, and dates inside 2016-10 → 2018-08. A synthetic row that
  references a non-existent real key is a generator bug, tested for.
- **V2-SYN-4.** Every synthetic table is **labelled synthetic in the catalog**,
  and **every answer that reads one says so** — in `scope`, in the caveats, and
  on screen. A figure derived from generated data must never be presentable as
  a measurement of the real business.
- **V2-SYN-5.** Every planted effect is recorded in
  `data/SYNTHETIC_GROUND_TRUTH.md`, which is the **evaluation answer key**
  (`DATA-4`). The agent never reads it; only scoring code does (`DATA-9`).

#### The ten synthetic tables

| Table | Grain | Key columns | Serves |
| --- | --- | --- | --- |
| `marketing_spend` | channel × day | `date`, `channel`, `customer_state`, `spend`, `impressions`, `clicks` | diagnostic, impact, scenario |
| `promotions` | promo × category × day | `promo_id`, `date`, `product_category`, `discount_pct`, `channel` | diagnostic (AOV dilution), scenario |
| `inventory_daily` | product × day | `date`, `product_id`, `units_on_hand`, `units_sold`, `stockout_flag` | diagnostic (stockouts), prescriptive |
| `web_traffic` | day × channel | `date`, `channel`, `sessions`, `bounce_rate`, `add_to_cart`, `checkout_starts` | diagnostic (funnel), impact |
| `price_history` | product × day | `date`, `product_id`, `list_price`, `effective_price` | **scenario (elasticity)**, diagnostic |
| `competitor_prices` | product × day | `date`, `product_id`, `competitor_price`, `competitor_name` | **scenario (elasticity)** |
| `customer_segments` | customer | `customer_unique_id`, `segment`, `ltv_band`, `acquisition_channel`, `assigned_at` | segment, prescriptive, impact |
| `regional_targets` | state × month | `month`, `customer_state`, `metric_id`, `target_value` | impact (attainment), prescriptive |
| `returns` | order item | `order_id`, `order_item_id`, `return_date`, `reason`, `refund_value` | diagnostic, impact |
| `delivery_sla` | carrier × state × day | `date`, `carrier`, `customer_state`, `promised_days`, `actual_days`, `sla_breach_flag` | diagnostic (the delay spike), prescriptive |

`customer_segments` keys on `customer_unique_id`, not `customer_id` —
deliberately, because that is the real identity column and conflating the two is
one of the traps the eval set tests (§3.5 I8).

#### The four planted effects

Documented with exact windows, magnitudes and true shares in
`data/SYNTHETIC_GROUND_TRUTH.md`. Each is designed to be *findable* by a
specific engine and to have a *confounder* that must not be mistaken for it.

| # | Effect | Window | Mechanism | Findable by | Confounder planted alongside |
| --- | --- | --- | --- | --- | --- |
| **E1** | **Marketing cut** | 2018-03 → 2018-05 | Paid-search spend cut ~40% in SP and RJ; traffic and order count follow with a ~2-week lag | `driver` + co-movement on `marketing_spend`, `web_traffic` | A category-mix shift in the same window that moves with the decline but is not driving it |
| **E2** | **Stockouts** | 2017-11 → 2017-12 | `stockout_flag` on the top 3 categories during the November peak; suppresses order count and item count | `driver` on `inventory_daily`, `anomaly` on the series | Black-Friday seasonality in the same weeks — a genuine seasonal peak the baseline must not read as the cause |
| **E3** | **Promo: orders up, AOV down** | 2018-01 → 2018-02 | A 20% discount lifts `order_count` ~15% while `aov` falls ~12%; GMV roughly flat | `driver` on `promotions`; **requires the ratio decomposition** — the whole point is that AOV moves for a mix/price reason, not a volume reason | A simultaneous payment-mix shift toward `boleto` |
| **E4** | **Delivery-delay spike** | 2018-06 | One carrier's `actual_days` jumps in the South; `sla_breach_flag` spikes; `review_score` drops with a ~3-week lag | `anomaly` on `delivery_sla`, then `driver` with a **lagged** co-movement test (`DRV-5`) | A freight-cost rise in the same month that is a *consequence*, not a cause — tests reverse-causation discipline |

**These are co-movement evidence, not proof.** The generator knows the true
mechanism; the agent does not. Every diagnostic answer over these effects is
capped at the evidence grade its method earns (`EVID-1`), carries the
causal-boundary note (`DRV-9`, `E5`), and E4's confounder exists specifically to
catch an agent that would claim causation from correlation.

### 2.3 Layer 3 — ingestion [S]

`scripts/ingest.py` registers a folder of CSVs as tables in the semantic layer:
profile columns, infer grain, propose join edges for human approval
(`GRD-2`), mark the source as user-supplied, and bump `catalog_version`. It is
the path by which a reviewer can point the agent at their own data. It is
read-only onboarding — it never writes to a warehouse (`SAFE-2`).

### 2.4 The `semantics/` folder

Prose that the catalog cannot hold, versioned beside the data:

| File | Holds |
| --- | --- |
| `semantics/<table>.md` | per-table notes: what a row means, grain, gotchas, which columns are synthetic |
| `semantics/metrics.md` | every governed metric: definition, formula in words, required filters, aggregation class, caveats |
| `semantics/glossary.md` | business terms → governed names ("active customer", "margin", "region") |
| `semantics/RULES.md` | the analysis rules of this warehouse: the truncation rule, the `customer_id` vs `customer_unique_id` rule, non-additive metrics, which tables are synthetic |

`semantics/RULES.md` is **retrieved into the prompt** for understanding and
planning. It is instructions for *the agent's own reasoning*, never a source of
figures.

---

## 3. The eight intents, with ten grounded examples each

Notation per row: **the question** → *expected intent*, the tools it needs, and
what the answer must contain or refuse. `✎` marks a question whose correct
answer is a refusal or a clarification — these are **not** failures; they are
the behaviour `ABS-1`/`ABS-4` require and belong in the eval set
(`EVAL-2`).

### 3.1 `discovery` — "what data do you have?"

Answered from `catalog` only. No SQL execution, no figures beyond governed
counts the catalog itself holds.

| # | Question | Layer | Expected answer content |
| --- | --- | --- | --- |
| D1 | **"What data do you have?"** ★ | R+S | All 19 tables grouped by subject, row counts, date span, **and which are synthetic**. Must answer — see §9. |
| D2 | "Which metrics can you calculate?" | R+S | The 9 governed metrics plus the synthetic-layer metrics (spend, sessions, SLA breach rate, return rate), with their definitions and layer. |
| D3 | "What time period does the data cover?" | R+S | 2016-09-04 → 2018-10-17 real, **and** the truncation note (V2-DATA-3); synthetic covers 2016-10 → 2018-08. |
| D4 | "Can I break revenue down by region?" | R | Yes — `customer_state`, 27 values; plus `customer_city`, `seller_state`. |
| D5 | "What dimensions are available for AOV?" | R | The registry's `allowed_dimensions` for `aov`, including `payment_type`. |
| D6 | "How is revenue defined here?" | R | `revenue` formula, base table `order_payments`, required filters, caveats — from `semantics/metrics.md`. |
| D7 | "What's the difference between GMV and revenue?" | R | GMV is `order_items` price at `order_item` grain; revenue is `order_payments` at `order` grain. Grain difference stated. |
| D8 | "Do you have marketing or traffic data?" | S | Yes — `marketing_spend`, `web_traffic`, `promotions`, **clearly labelled synthetic**, with their grains. |
| D9 | "How many customers are in the database?" | R | 99,441 customer rows; `customer_unique_id` is the identity column — the distinction stated, not elided. |
| D10 | ✎ "Do you have customer age or gender?" | — | **Refusal** naming the missing attributes, listing what *is* held about a customer (state, city, zip prefix, and the synthetic segment), and offering the nearest answerable question. This stays a refusal: the attribute genuinely does not exist in either layer. |

### 3.2 `clarify` — "what exactly do you mean?"

Produces one question with 2–4 options and a stated default. Round ≤ 2.

| # | Question | What must be asked back |
| --- | --- | --- |
| C1 | "Summarize revenue" | Which window? Options: 2018 YTD to last complete month · full history · last 12 complete months. Default: last 12 complete months. |
| C2 | "How are sales doing?" | Which metric — `revenue`, `gmv` or `order_count`? Default: `revenue`. |
| C3 | "Show me the top states" | Top by which metric, and over what window? |
| C4 | "Why did it drop?" (no prior turn) | Which metric and which period dropped? |
| C5 | "Compare the two biggest regions" | Confirm SP and RJ by order volume, and name the metric to compare. |
| C6 | "What about last month?" (no prior turn) | There is no prior question to extend; name the metric. |
| C7 | "Revenue by category — recent" | "Recent" is undefined: last complete month (2018-08) · last quarter · last 90 days. |
| C8 | "Is freight expensive?" | "Expensive" needs a comparison: versus other states · versus order value · versus last year. |
| C9 | "Give me the numbers for SP" | `SP` resolves to `customer_state`; which metric and window? |
| C10 | "Show growth" | Growth of which metric, between which two periods, at what grain? |

**Clarify is bounded.** Round 1 asks; round 2 may ask once more only if the
first reply introduced a *new* ambiguity. Round 3 is forbidden — the agent
proceeds on the stated default assumption and records it in
`AnswerEnvelope.assumptions`.

### 3.3 `descriptive` — "what?"

SQL only, via the governed compiler where coverage is full. This is what V1
already does; it is listed so V2 regression-tests it unchanged.

| # | Question | Layer | Notes |
| --- | --- | --- | --- |
| S1 | "How many orders were there in August 2018?" *(a verified V1 chip)* | R | |
| S2 | "What was revenue in 2017?" | R | |
| S3 | "What was GMV by customer state in 2018?" | R | |
| S4 | "How did revenue in 2018 compare to 2017?" *(a verified V1 chip)* | R | |
| S5 | **"What are the spikes across all months?"** ★ | R+S | **Answered from the precomputed `analytical_anomalies` table**, not by scanning 9 metrics × 23 months live. One `analytical_table` read, ranked by score, with `spike`/`dip` labels. Must answer — see §9. |
| S6 | "Which product categories had the highest GMV in 2017?" | R | |
| S7 | "What was the cancellation rate by month in 2018?" | R | |
| S8 | "How many unique customers ordered in Q2 2018?" | R | `customer_unique_id` |
| S9 | "What was the average review score by state in 2018?" | R | |
| S10 | "What was marketing spend by channel in 2018?" | S | Labelled synthetic |

S5 is why Track 1 precomputes anomalies and forecasts. Asked live, "what are
the spikes across all months" is a multi-series scan — 9 metrics × 23 periods,
FDR-corrected — which blows the latency budget and the query budget. Precomputed
nightly into an analytical table, it is a single indexed read. The engine still
produced every figure; the table is a *cache of engine output*, not a
substitute for it.

### 3.4 `diagnostic` — "why?"

`anomaly` establishes whether the change is outside the expected range;
`driver` attributes it. **Both must run** for a "why" question — V1's rule
signal already emits `("anomaly", "driver")` for these (`router.py:744`), but
the driver step raises before it returns. Fixing that is a V2 prerequisite, not
a V2 feature.

V2's diagnostic method is: **additive contribution** over governed dimensions,
then **correlation with significance** against synthetic operational indicators,
then **feature importance** over a fitted model where the indicator set is wide
— each result carrying an evidence grade and the causal-boundary note.

| # | Question | Layer | Needs | Planted effect |
| --- | --- | --- | --- | --- |
| G1 | **"Why did revenue drop in the top category in April 2018?"** ★ | R+S | anomaly + driver over `product_category`, then co-movement on `marketing_spend` and `web_traffic` | **E1** — must identify the marketing cut and *not* the category-mix confounder |
| G2 | "Was order count unusual in August 2018?" *(a verified V1 chip)* | R | anomaly only — the question asks only the first half | — |
| G3 | "Why did order count fall in December 2017?" | R+S | anomaly + driver, co-movement on `inventory_daily` | **E2** — stockouts, separated from Black-Friday seasonality |
| G4 | "Why did AOV fall in January 2018?" | R+S | driver on a **ratio** metric + `promotions` | **E3** — the promo; requires numerator/denominator decomposition |
| G5 | "Why did review scores drop in June 2018?" | R+S | anomaly, then **lagged** co-movement on `delivery_sla` | **E4** — the delay spike, with the freight rise correctly identified as a consequence |
| G6 | "What drove the GMV change between Q1 and Q2 2018?" | R | driver, `product_category` | — |
| G7 | "Why is AOV higher for boleto than credit card?" | R | driver over `payment_type` — a *cross-section*, not a time comparison | — |
| G8 | "Which states drove the revenue decline in May 2018?" | R+S | driver, `customer_state`, + regional `marketing_spend` | **E1** tail |
| G9 | "Why did cancellations rise in 2018 versus 2017?" | R+S | driver on a **rate** metric; denominators carried, not just numerators; `returns` as an indicator | — |
| G10 | ✎ "Did the carrier cause the delivery delays?" | S | Answer at the grade the method earns (≤ 3 via difference-in-differences against unaffected carriers), **with** the causal-boundary note and no "caused" | **E4** |

G4 and G9 are deliberate traps: `review_score` is a mean and
`aov`/`cancellation_rate` are ratios, so additive attribution is wrong
arithmetic — `DRV-2` requires contributions to reconcile to the total change.
The engine detects the metric's `aggregation` class and switches to a
numerator/denominator decomposition. **E3 is planted precisely so this path has
a right answer to find**: orders up, AOV down, GMV flat is only explicable if
the engine decomposes the ratio rather than forcing a share on it.

G10 is no longer a refusal. The synthetic layer contains unaffected carriers in
the same window, so a difference-in-differences comparison is available
(`DRV-6`) and the honest answer is grade 3 — "the delay was specific to this
carrier; control carriers were stable" — plus the boundary note. That is more
useful than refusing, and still never says "caused".

### 3.5 `impact` — "so what?"

Turns a finding into money or share. Every figure comes from
`python.impact` over SQL rows.

| # | Question | Layer | Impact figure |
| --- | --- | --- | --- |
| I1 | **"How much did the April 2018 drop cost us?"** ★ | R+S | Gap versus the anomaly baseline, in BRL, with interval. Must answer — see §9. |
| I2 | "What is SP worth to us?" | R | Share of total revenue and GMV, last 12 complete months |
| I3 | "How much revenue is exposed to the top 3 categories?" | R | Concentration with an interval |
| I4 | "What would closing the cancellation gap be worth?" | R | Cancelled-order value at current AOV, stated as an upper bound |
| I5 | "What was the return on the marketing spend we cut?" | S | Revenue change per BRL of spend over E1's window, stated as an observed ratio, **not** a causal ROI |
| I6 | "Which state's revenue decline mattered most in 2018?" | R | Absolute contribution ranked, not percentage — a 40% fall in a tiny state is not the biggest problem |
| I7 | "How far are we off the regional targets?" | S | Attainment versus `regional_targets`, by state, with the gap in BRL |
| I8 | "How much of 2018 GMV came from repeat customers?" | R | Needs `customer_unique_id`, not `customer_id` — the trap is stated in the answer |
| I9 | "What are the stockouts costing us?" | S | Forgone units × measured price over E2's window, as an upper bound with the assumption stated |
| I10 | "How big is the 2018 revenue shortfall versus 2017?" | R | Measured difference, with the truncation caveat and **aligned windows** |

I10 is a trap: comparing full-year 2017 with "2018" invites comparing 12
months with 8. The engine must align windows and say that it did.

I5 is the discipline case for this intent: "return on spend" is a *ratio of two
measured changes*, and calling it an ROI implies the spend caused the revenue.
The engine reports the observed ratio with the co-movement grade and the
boundary note. It answers; it does not overclaim.

### 3.6 `forecast` — "what next?"

`python.forecast` — **Prophet** (`ds`/`y`, `make_future_dataframe`, `predict`
yielding `yhat`/`yhat_lower`/`yhat_upper`, with trend and seasonality
components exposed) and an **automatic ETS fallback** when Prophet is
unavailable or fails to converge. The method actually used, and why, is always
reported. Anchored on `last_complete_period` = 2018-08.

| # | Question | Notes |
| --- | --- | --- |
| F1 | **"Forecast revenue for the next 3 months"** ★ | Horizon 3, anchored 2018-08, interval required. Must answer — see §9. |
| F2 | "Where is order count heading?" | Horizon default 3, trend + interval |
| F3 | "Forecast GMV for the next quarter" | Horizon = 1 quarter at month grain = 3 periods |
| F4 | "What is the expected AOV next month?" | Ratio metric — forecast numerator and denominator, then form the ratio |
| F5 | "Project revenue for SP over the next 6 months" | Filtered series; interval widens — reported, not smoothed away |
| F6 | "Will cancellations keep rising?" | Direction + interval; if the interval spans zero slope, the honest answer is "no detectable trend" — stated, not refused |
| F7 | "How many customers will we have next quarter?" | `customer_count` is non-additive across periods — the engine states the definition it forecast |
| F8 | "Forecast review scores for the next 3 months" | Bounded 1–5; the interval must respect the bound |
| F9 | "What will revenue be in 2020?" | 16 periods on 23 of history. **Answer the defensible horizon** (3–6 periods) with its interval, and say plainly that beyond that the interval is wider than the signal. Name the limit; do not refuse the question. |
| F10 | "Forecast revenue for the next 3 months by category" | 71 series on thin history. **Answer for the top N by revenue** (default 5, covering the bulk), report the aggregate for the remainder, and state the cut. |

F9 and F10 changed from refusals to **bounded answers** under V2-ANS-1. The
engine still refuses to *extrapolate* beyond what the data supports — it simply
delivers what it can and names the boundary, rather than returning nothing. This
is `ABS-3` as a gate: refusing a whole class because part of it is
unsupportable is the over-refusal the reviewers saw.

### 3.7 `scenario` — "what if?"

`python.scenario` re-runs a **fitted** relationship under a stated input change.
It never invents a coefficient — but with the synthetic layer, far more
relationships are now genuinely fittable, including **price elasticity**.

**Price elasticity is in scope.** `price_history` and `competitor_prices` give
per-product price variation over time alongside realised volume, so a
log-log demand elasticity is estimable with `statsmodels` — per category, with
standard errors, a confidence interval, and controls for promotions and relative
competitor price. Mandatory labelling: the estimate is **based on synthetic
data** (V2-SYN-4), and its assumptions are stated — no randomised price
experiment, so the estimate is observational and confounded by anything that
moved price and demand together.

| # | Question | Layer | Scenario parameter / fit |
| --- | --- | --- | --- |
| X1 | "What if freight costs rise 10%?" | R | `freight_value × 1.10` propagated to the GMV/freight ratio |
| X2 | "What if we lose SP entirely?" | R | Remove a dimension value, re-aggregate |
| X3 | "What if the cancellation rate halved?" | R | Rate change → recovered order value at measured AOV |
| X4 | "What if credit card share grew to 85%?" | R | Mix shift across `payment_type`, holding per-type AOV |
| X5 | "What if AOV improved 5% next quarter?" | R | Forecast + multiplicative shock, interval carried through |
| X6 | **"What if we raise prices 5%?"** ★ | S | **Fitted elasticity** from `price_history` + `competitor_prices`; demand and revenue response with an interval. Must answer — see §9. |
| X7 | "What if we restored the marketing spend we cut?" | S | Fitted spend→orders response over E1's window, with lag |
| X8 | "What if order volume grew 10% but AOV fell 5%?" | R | Two simultaneous shocks composed by the engine, not multiplied in prose |
| X9 | "What if we eliminated the stockouts?" | S | Forgone demand from E2 recovered at measured price, as an upper bound |
| X10 | ✎ "What if we launched in Argentina?" | — | **Refuse.** There is no Argentina in either layer — no market, no customers, no prices, nothing to fit. Name what is missing and offer the nearest answerable question (expansion into an under-served Brazilian state). |

The discipline of this intent is unchanged, only better supplied: **a scenario
is only as good as the fit behind it**, and a scenario with no fit is a
fabricated number. What changed is that elasticity now *has* a fit, so refusing
it would be over-refusal rather than rigour. X10 shows where the line still is —
not "the estimate would be uncertain", but "the input does not exist".

Every elasticity answer carries, non-negotiably: the point estimate with its
interval, the R² or equivalent fit quality, the controls included, the
synthetic-data label, and the sentence that this is an observational estimate,
not an experiment.

### 3.8 `prescriptive` — "now what?"

Ranks actions over *already quantified* outputs (`REC-2`). Produces no new
figures of its own.

| # | Question | Layer | Requires upstream |
| --- | --- | --- | --- |
| P1 | **"Which customer segment should we target?"** ★ | S | `customer_segments` + impact ranking by LTV band and acquisition channel. Must answer — see §9. |
| P2 | "What should we do about the April revenue decline?" | R+S | diagnostic E1 + impact |
| P3 | "Where should we focus to grow GMV next quarter?" | R+S | forecast + impact |
| P4 | "Which states should we prioritise?" | R+S | impact ranking + `regional_targets` attainment |
| P5 | "How do we reduce cancellations?" | R+S | diagnostic on `cancellation_rate` + `returns` |
| P6 | "What should we do about the delivery delays?" | S | diagnostic E4 + `delivery_sla` by carrier |
| P7 | "Which categories deserve more inventory?" | S | forecast per category (top N per F10) + `inventory_daily` stockout history |
| P8 | "Should we run the promotion again?" | S | diagnostic E3 — orders up but AOV down, so the answer must weigh both, not cite the order lift alone |
| P9 | "Should we match competitor prices?" | S | elasticity X6 + `competitor_prices` |
| P10 | "What should I watch next month?" | R+S | Monitoring list from the precomputed anomalies table, with thresholds from the anomaly engine |

P8 is the prescriptive trap that pairs with E3: a recommendation drawn from
"orders rose 15%" alone is wrong, because AOV fell 12% and GMV was flat. The
ranking must use the *net* quantified impact (`REC-2`), which is exactly why
impact figures must come from an engine and not from a narrative.

Every prescriptive answer carries 2–3 options with assumptions, trade-offs,
sensitivity to the key assumption, what to monitor, and what data would change
the ranking (`REC-3`). **The agent recommends; a person decides** (`REC-5`) —
unchanged from V1.

---

## 4. Compound questions

A compound question carries **several intents in one utterance**. V1's router
can emit multiple route labels but the orchestrator only ever executes the
primary one (`orchestrator.py:166-213`), so the second half is silently dropped.
V2 requires the planner to produce one step per intent and the envelope to
answer every part it accepted.

| # | Question | Decomposition | Shared work |
| --- | --- | --- | --- |
| K1 | "How does revenue trend look today and what will it be in 3 months?" | `descriptive` + `forecast` | one series query feeds both |
| K2 | "Was August unusual, and why?" | `diagnostic` (anomaly → driver) | driver reuses the anomaly's baseline |
| K3 | "Why did revenue fall and what should we do?" | `diagnostic` + `impact` + `prescriptive` | prescriptive ranks the impact output |
| K4 | "What's our biggest state and what happens if we lose it?" | `descriptive` + `scenario` | scenario takes the descriptive's answer as its target |
| K5 | "Show me revenue by category and forecast the top three" | `descriptive` + `forecast` | the forecast's scope depends on the descriptive's *result* — a genuine data dependency, not just ordering |
| K6 | "Is the cancellation rate rising, why, and what is it costing us?" | `diagnostic` + `impact` | |
| K7 | "Compare 2017 and 2018 and tell me what to watch" | `descriptive` + `prescriptive` | |
| K8 | "What data do you have on freight, and is it unusual this year?" | `discovery` + `diagnostic` | discovery first; it may make the second half refusable |
| K9 | "Forecast revenue and tell me what happens if freight rises 10%" | `forecast` + `scenario` | the scenario *requires* the forecast's fit |
| K10 | "Why did August fall, what did it cost, and what should we do?" | the full `diagnostic` → `impact` → `prescriptive` chain | the V2 flagship path |

**Rules.**

1. **A compound question is one run, one envelope.** Not N runs.
2. **Partial success is reported, not hidden.** If K9's forecast refuses the
   horizon, the scenario step is `skipped` with a stated reason and the
   envelope says so. Reporting half an answer as a whole answer is the failure
   mode V2 is being built to remove.
3. **Shared work is executed once.** K2's driver step reuses the anomaly
   baseline; the query budget (`max_queries`, default 3) is a per-run budget and
   compound questions must be planned to fit it or raise it explicitly —
   K10 needs more than 3 queries, so V2 must set per-intent budgets
   (`OPS-2`, `OPS-6`).
4. **Depth is capped** (`RTE-6`). A plan deeper than 5 steps falls back to the
   highest-value single intent plus a stated omission.

---

## 5. Vague questions

A vague question is one that **cannot be resolved to (metric, window, grain)**
without a choice. V2's handling is: resolve what is resolvable, ask about
exactly one thing, and state the default.

| # | Question | Resolved without asking | The one question asked | Default if unanswered |
| --- | --- | --- | --- | --- |
| V1 | "Summarize revenue" | metric = `revenue`, grain = month | window | last 12 complete months |
| V2 | "How's business?" | nothing | metric | `revenue`, monthly, last 12 complete months |
| V3 | "Anything unusual?" | intent = `diagnostic` | which metric to scan | scan all 9 governed metrics at month grain, FDR-corrected (`ANOM-6`) |
| V4 | "Give me an overview" | nothing | metric set | `revenue` + `order_count` + `aov`, last complete month vs. prior |
| V5 | "What's wrong?" | intent = `diagnostic` | metric and window | the most recent complete month, all metrics |
| V6 | "Tell me about SP" | filter = `customer_state = 'SP'` | metric | `revenue`, last 12 complete months |
| V7 | "Recent performance" | grain = month | metric and "recent" | `revenue`, last 3 complete months |
| V8 | "Best and worst" | nothing | metric and dimension | `revenue` by `customer_state` |
| V9 | "Is growth good?" | intent = `descriptive` comparative | metric and the two periods | `revenue`, last complete month vs. same month prior year |
| V10 | "Break it down" | — (needs a prior turn) | with no context: metric and dimension | — |

**V3 and V5 are the interesting ones.** "Anything unusual?" is a *scan*, not a
lookup: it runs the anomaly engine across many series, which `ANOM-6` requires
to control false discoveries and report the correction used. A vague question
can therefore be more expensive than a precise one, which is why
`discovery`/`clarify` sit in front of it.

**V10 is unanswerable without context** — which is the next section.

---

## 6. Follow-ups

A follow-up inherits from the conversation. This is the largest behavioural gap
in V1: `session_id` is stored and never read, so **every follow-up is treated as
a cold question**. "What about SP?" routes to `clarify` today, and should.

### 6.1 The eight follow-up shapes

| Shape | Example | Inherits | Overrides |
| --- | --- | --- | --- |
| **Filter swap** | "What about SP?" | metric, window, grain, intent | filter |
| **Window shift** | "And last year?" | metric, grain, filters, intent | window |
| **Intent escalation** | "Why?" | metric, window, filters | intent → `diagnostic` |
| **Intent escalation** | "Forecast that" | metric, filters, grain | intent → `forecast` |
| **Drill-down** | "Break that down by category" | metric, window, filters | adds a dimension |
| **Grain change** | "Weekly instead" | everything | grain |
| **Metric swap** | "Same for GMV" | window, grain, filters, intent | metric |
| **Reference** | "Why is that number so low?" | the *resolved* prior turn, including the figure referenced | intent → `diagnostic` |

### 6.2 Worked examples

| # | Turn 1 | Follow-up | Resolves to |
| --- | --- | --- | --- |
| U1 | "What was revenue in 2018?" | "What about SP?" | revenue, 2018, `customer_state='SP'`, `descriptive` |
| U2 | "What was revenue in 2018?" | "Why?" | ✎ Ambiguous — "why" needs a *change*, and turn 1 was a single total. Clarify: "Why compared to what — 2017, or the monthly trend within 2018?" |
| U3 | "Revenue fell in August 2018." | "Why?" | `diagnostic`, revenue, 2018-08 vs. 2018-07 |
| U4 | "What's revenue by state?" | "Forecast that" | ✎ 27 series. Clarify down to top N, or forecast the aggregate — same rule as F10. |
| U5 | "Revenue monthly in 2018" | "Forecast that" | `forecast`, revenue, month grain, horizon 3, anchored 2018-08 |
| U6 | "Order count in August 2018" | "And July?" | `descriptive`, order_count, 2018-07 |
| U7 | "GMV by category in 2018" | "Just the top 5" | same query, `limit` 5 — no new SQL needed if the rows are already held |
| U8 | "Why did revenue spike in Nov 2017?" | "What did it add?" | `impact` over the existing driver output |
| U9 | "Forecast revenue" | "What if freight rises 10%?" | `scenario` over the forecast fit from the prior turn |
| U10 | "Revenue in 2018" · "What about SP?" · "And RJ?" · "Why is RJ lower?" | A 4-turn chain: the third turn inherits from the *second*, not the first; the fourth escalates intent while keeping RJ | |

### 6.3 Rules

1. **Context is read, never invented.** A follow-up resolves against the stored
   `ResolvedQuestion` of a prior turn (see [`contracts.md`](contracts.md) §1–2).
   If no prior turn exists, the follow-up is `clarify` — U2 and V10 show this is
   sometimes the *correct* answer even when context exists.
2. **The resolution is shown.** Every follow-up answer states what it inherited:
   "Revenue, 2018, filtered to SP — carried from your previous question." A
   silently inherited filter is how a user ends up trusting the wrong number.
3. **Context expires.** Bounded to the last `N` turns of one `session_id`
   (proposed `N = 10`). It is per-session, never cross-user, and is scoped by
   permission like the cache (`OPS-4`).
4. **Numbers are never inherited, only *references* to them.** U8's "what did it
   add" re-reads the prior turn's claim by id and re-runs the impact engine over
   the stored rows. The prior figure is not retyped into a prompt and
   re-emitted — that would launder a number out of its evidence link and break
   `SAFE-3`.

---

## 7. The must-answer set ★

These nine questions are **demo-critical**. Each is marked ★ above. They are the
questions a reviewer will actually type, and V1 fails or clarifies on most of
them. In V2 each one **must return `status: "answered"`** with a conclusion,
evidence, and at least one claim.

> **V2-ANS-2.** A must-answer question returning `clarify`, `refused`,
> `insufficient_evidence` or `error` is a **failing gate**, not a tuning issue.
> Verified on every tag by `verify:live` and by the eval suite.

| ★ | Question | Intent | Ref | Why V1 fails it today |
| --- | --- | --- | --- | --- |
| 1 | "What data do you have?" | `discovery` | D1 | No discovery intent exists; routes to `clarify` |
| 2 | "Why did revenue drop in the top category in April 2018?" | `diagnostic` | G1 | Driver route raises `TypeError` (V2-PRE-1) |
| 3 | "How much did the April 2018 drop cost us?" | `impact` | I1 | No impact intent or engine |
| 4 | "What about SP?" *(as a follow-up)* | follow-up | U1 | `session_id` never read; routes to `clarify` |
| 5 | "Forecast revenue for the next 3 months" | `forecast` | F1 | No forecast intent or engine |
| 6 | "What if we raise prices 5%?" | `scenario` | X6 | No scenario intent; no elasticity fit |
| 7 | "Which customer segment should we target?" | `prescriptive` | P1 | `next_actions` hardcoded `()`; no segments table |
| 8 | "How does revenue trend look today and what will it be in 3 months?" | compound | K1 | Only the primary route executes; second half dropped |
| 9 | "What are the spikes across all months?" | `descriptive` | S5 | Multi-series scan exceeds query and latency budgets |

**Each must-answer question needs a named owner track and an acceptance test.**
Five of the nine depend on the synthetic layer, which is why Track 1 is first
after Track 0.

---

## 8. What V2 explicitly does not add

Stated so the boundary stays legible, in the spirit of `A3`:

| Not built in V2 | Why |
| --- | --- |
| Free-form model-written Python | `ANA-2`, `B0`. Engines are a closed registry. |
| Autonomous action execution | `REC-5`. The agent recommends; a person decides. |
| Causal inference beyond grade 4 | `E5`. Co-movement and DiD are the ceiling this data supports. |
| Experimental causal identification | No randomisation exists; the elasticity estimate is observational and labelled as such (X6). |
| Modifying the real snapshot | V2-SYN-1. `brazil_ecommerce.sqlite` is read-only, always. |
| Presenting synthetic figures as real | V2-SYN-4. Every synthetic-derived answer is labelled. |
| Multi-turn dialogue *management* | Context is a bounded inheritance of resolved slots, not a learned dialogue policy (`A3`). |
| Cross-session memory | Per-`session_id` only. |
| Write access of any kind | `SAFE-2`. There is no write path and V2 adds none. |

---

## 9. Acceptance for this document

`scope.md` is accepted when:

1. All 80 intent examples, 10 compound, 10 vague and 10 follow-up questions are
   entered into the eval suite as `EvalCase` rows with an `expected.intent`, and
   the `✎` rows carry `expected.refusal` or an expected clarification
   (`EVAL-2`, `D2`).
2. **All nine must-answer questions (§7) return `status: "answered"`.** This is
   a hard gate (V2-ANS-2).
3. Every `✎` row has a test asserting the refusal *names the missing thing*
   (`ABS-1`), and the over-refusal rate is reported and within threshold
   (`ABS-3`). Only D10 and X10 remain refusals; both refuse because an input
   genuinely does not exist.
4. The truncation rules V2-DATA-1..3 have unit tests on the real snapshot.
5. The synthetic rules V2-SYN-1..5 have tests: the real database is unmodified
   (checksum), generation is byte-identical under a fixed seed, every synthetic
   foreign key resolves to a real one, every synthetic table is catalog-labelled,
   and every planted effect in §2.2 is recoverable by its named engine while its
   confounder is *not* reported as the driver.
6. No example in this file requires a number that does not come from SQL or a
   registered engine (`SAFE-8`, `SAFE-3`) — verified by an architecture test.
