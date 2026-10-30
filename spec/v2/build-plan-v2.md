# V2 Build Plan — Five Tracks

**Location in repo:** `spec/v2/build-plan-v2.md`
**Status:** **approved** with overrides recorded in §11. Branch:
`major-project-update`.
**Companions:** [`scope.md`](scope.md), [`contracts.md`](contracts.md)
**Governing specs:** [`requirements.md`](../requirements.md), [`build-plan.md`](../build-plan.md)

---

## 0. Principles carried over, unchanged

1. **Traceability.** Every commit cites requirement IDs. V2 adds the `V2-*` IDs
   defined in this file and in `scope.md`.
2. **SAFE-8 is the design constraint, not a check at the end.** A language model
   never computes a number. V2's new work is *understanding and planning*; every
   figure comes from SQL or a registered Python engine and is linked to an
   evidence claim.
3. **Answer, with stated assumptions** (V2-ANS-1). Refuse only when an input
   genuinely does not exist. The nine must-answer questions (`scope.md` §7) are
   a hard gate, not a target.
4. **Closed registries only.** No free-form model-written code, no `eval`, no
   tool string the planner can invent (`ANA-2`, `B0`).
5. **Do not change V1 behaviour until its track says to.** Track 0 is the only
   place existing behaviour changes, and it changes it because it is broken.

---

## 1. Track 0 — Prerequisites (must land before Tracks 1–5 are useful)

Not one of the five tracks; a short blocking list. These are V1 defects, found
while writing `scope.md`, that make V2 work unverifiable.

| ID | Item | File | Why it blocks | Status |
| --- | --- | --- | --- | --- |
| V2-PRE-1 | **The driver route raises on every call.** `_contribution_table(current_execution, comparison_execution, …, current=…, comparison=…)` passes `current` twice; the signature takes `current_period`/`comparison_period`. | `backend/src/orchestrator.py:518` | "Why" is unreachable live. Every diagnostic and compound example in `scope.md` §3.4 and §4 fails for this reason alone. Independently reproduced; also recorded as gap 14 in `frontend/web/CLAUDE.md`. | **approved, own commit** |
| V2-PRE-2 | **Per-intent budgets.** `max_queries` defaults to 3; K10 needs 4+. | `contracts/models.py:984`, `orchestrator.py:_execute` | Compound plans silently hit `BudgetExceeded` and report an error instead of an answer (`OPS-2`, `OPS-6`). | **approved, own commit** |
| V2-PRE-3 | **`last_complete_period` in the semantic layer.** | new, Track 1 | Without it every forecast and scenario fits on 2018-09 (16 orders) and 2018-10 (4 orders) and produces a false collapse (`scope.md` §2.1, V2-DATA-1..3). | Track 1 deliverable |

**Acceptance.** V2-PRE-1 has a regression test asserting a driver question
returns `status: "ok"` with a populated `DriverResult`; V2-PRE-2 has a test that
a 4-query plan completes; V2-PRE-3 is Track 1's first deliverable. The existing
232 tests stay green.

---

## 2. The five tracks

```
Track 0  Prerequisites ──┐
                         ├──> Track 1  Data & semantic layer ──┐
                         │                                     ├──> Track 3  Understanding & planning ──┐
                         └──> Track 2  Python engines ─────────┘                                        ├──> Track 5  UI/UX & visualization
                                                                    Track 4  Context & discovery ───────┘
```

| Track | Owner | Produces | Depends on |
| --- | --- | --- | --- |
| **1 — Data & semantic layer** | BE-2 | Completeness metadata, analytical tables, catalog/discovery surface | Track 0 |
| **2 — Python engines** | AN-1 | `forecast`, `impact`, `scenario`, `segment` engines | Track 0, Track 1 (for tables) |
| **3 — Understanding & planning** | BE-1 | Intent classifier, resolver, planner, step executor | Track 1, Track 2 (for the tool registry) |
| **4 — Context & discovery** | BE-1 | `ContextState`, follow-up resolution, discovery intent, clarification rounds | Track 3 |
| **5 — UI/UX & visualization** | FE-1 | `VisualizationSpec` rendering, step view, follow-up chips, assumptions panel | Track 3, Track 4 |

**Order.** Track 1 and Track 2 can run in parallel after Track 0. Track 3 needs
both. Track 4 needs Track 3's `ResolvedQuestion`. Track 5 needs an envelope to
render, so it starts against fixtures (`contracts/examples/v2/`) on day one and
switches to the live backend when Track 3 lands — the same pattern the existing
frontend already uses via `?mock=1`.

**Contracts first.** `backend/src/contracts/v2.py` is written once, before all
five tracks, so every track codes against the same frozen models. That is the
single implementation step authorised after this plan is approved.

---

## 3. Track 1 — Data and semantic layer

**Goal.** Make the warehouse describable, make time windows honest, and **give
the agent something to diagnose with**. This track is the largest in V2 and the
one most other tracks wait on: five of the nine must-answer questions need the
synthetic layer.

### Files owned

| File | New? | Purpose |
| --- | --- | --- |
| `scripts/synth/generate.py` | new | Seeded synthetic generator; writes `data/brazil_ecommerce_v2.sqlite` |
| `scripts/synth/plants/*.py` | new | One module per planted effect (E1–E4), each writing its manifest entry |
| `scripts/synth/manifest.py` | new | Ground-truth writer → `data/SYNTHETIC_GROUND_TRUTH.md` + machine-readable sidecar |
| `scripts/ingest.py` | new | CSV folder → profiled, registered semantic-layer tables |
| `scripts/build_analytical_tables.py` | new | Precompute series, anomalies and forecasts (`GRD-12`) |
| `semantics/*.md` | new | Per-table notes, `metrics.md`, `glossary.md`, `RULES.md` |
| `backend/src/semantic/completeness.py` | new | `last_complete_period` per metric and grain |
| `backend/src/semantic/tables.py` | new | Registry of analytical tables, grains, freshness, `is_synthetic` |
| `backend/src/semantic/discovery.py` | new | Catalog-backed answers for the `discovery` intent |
| `backend/src/semantic/layers.py` | new | `data_layer` computation from tables read (SY-2) |
| `backend/src/catalog/registry.py` | extend | `aggregation`, `completeness_rule`, `is_synthetic` per metric; synthetic-layer metrics |
| `backend/src/knowledge/catalog_api.py` | extend | Expose descriptions and `semantics/` prose for discovery |
| `backend/tests/test_synth_generator.py`, `test_semantic_completeness.py`, `test_discovery.py`, `test_analytical_tables.py`, `test_ingest.py` | new | |

### Work

**1. Synthetic generator** (`scope.md` §2.2). Seeded, deterministic, pandas +
numpy; SDV and Mimesis optional behind a `[synth]` extra so the core install
stays light. Copies the nine real tables verbatim into
`data/brazil_ecommerce_v2.sqlite`, then generates the ten synthetic tables keyed
to real `order_id` / `product_id` / `seller_id` / `customer_unique_id`, the 71
real categories, the 27 real states, and dates confined to **2016-10 → 2018-08**
(complete periods only).

**The original `brazil_ecommerce.sqlite` is never opened for writing** — the
generator connects to it read-only (`?mode=ro`) exactly as the gateway does, and
a test asserts its checksum is unchanged after a generation run (V2-SYN-1).

**2. The four planted effects** as plugin modules, following the existing
`PlantPlugin` protocol (`Interfaces.md` §7.2): E1 marketing cut, E2 stockouts,
E3 promo (orders up / AOV down), E4 delivery-delay spike. Each plants a
confounder alongside its effect, and **nothing is planted without a manifest
entry** (`DATA-4`). `data/SYNTHETIC_GROUND_TRUTH.md` is human-readable; a JSON
sidecar is what scoring code reads. Neither is on an agent-readable path
(`DATA-9`).

**3. `last_complete_period`** (V2-DATA-1). A period is complete when its
observed volume is within a configured factor of the trailing median for that
grain. On the real snapshot the rule must classify **2018-08 as the last
complete month** and flag 2018-09 (16 orders), 2018-10 (4 orders) and 2016-09.
Published per metric and grain, versioned with `catalog_version`.

**4. Metric `aggregation` metadata.** `revenue`, `gmv`, `freight_value`,
`item_count` → `sum`; `order_count`, `customer_count` → `count`; `review_score`
→ `mean`; `aov`, `cancellation_rate` → `ratio` with declared numerator and
denominator. This is what lets the driver engine decompose a ratio instead of
forcing a share on it (`scope.md` G4, G9) and the forecast engine project a
ratio's parts (`scope.md` F4).

**5. Analytical tables**, three kinds:

| Table | Content | Serves |
| --- | --- | --- |
| `analytical_series` | monthly metric series, total and by each governed dimension | every engine's input |
| `analytical_anomalies` | `kpi, date, grain, dimension, dimension_value, value, expected, delta, delta_pct, direction, score, flagged, correction, …` | **S5**, "what are the spikes across all months" |
| `analytical_forecasts` | `kpi, dimension, ds, yhat, yhat_lower, yhat_upper, model, model_fallback_reason, mape, …` | fast forecast reads, backtest reporting |

The last two hold **engine output**, so a `ToolResult` reading them sets
`provenance.source = "engine"` with the row's `engine_version`
(`contracts.md` AT-1). They are a cache of engine output, not a replacement for
it: a `catalog_version` mismatch is a cache miss that falls through to a live
engine call (AT-2).

**6. Ingestion** (`scripts/ingest.py`). Profile a CSV folder, infer grain,
propose join edges for human approval (`GRD-2`), mark the source
user-supplied, bump `catalog_version`. Read-only onboarding; no warehouse writes
(`SAFE-2`).

**7. `semantics/` folder** and **discovery surface**. The four prose files from
`scope.md` §2.4, plus catalog-backed answers for all ten discovery questions.
`semantics/RULES.md` is retrieved into the prompt for *reasoning*, never as a
source of figures.

### Acceptance criteria

| # | Criterion | Verification |
| --- | --- | --- |
| 1.1 | `brazil_ecommerce.sqlite` checksum is **identical** before and after a generation run; the generator opens it `?mode=ro` | UT (V2-SYN-1) |
| 1.2 | Same seed ⇒ byte-identical `brazil_ecommerce_v2.sqlite` across two runs on a clean checkout | UT (V2-SYN-2) |
| 1.3 | Every synthetic foreign key resolves to a real key; every synthetic date lies in 2016-10 → 2018-08; every category and state is a real one | UT (V2-SYN-3) |
| 1.4 | The database has **≥ 18 tables** (9 real + 10 synthetic = 19) and each synthetic one is catalog-flagged `is_synthetic` | UT, INS |
| 1.5 | Each of E1–E4 is **recoverable by its named engine**, and each confounder is **not** reported as the driver | EV against the manifest (`DATA-4`, `ANA-5`) |
| 1.6 | Every planted effect has a manifest entry; nothing is planted without one; the manifest is not on an agent-readable path | INS (`DATA-4`, `DATA-9`) |
| 1.7 | `last_complete_period("revenue","month") == "2018-08"`; 2018-09, 2018-10, 2016-09 flagged incomplete | UT on the real snapshot |
| 1.8 | All 9 governed metrics declare an `aggregation`; ratio metrics declare numerator and denominator | UT, INS |
| 1.9 | A `descriptive` answer whose window includes an incomplete period carries a caveat naming the period and its observed volume | UT (V2-DATA-3) |
| 1.10 | **S5 answers from `analytical_anomalies` in one read**, within the lookup latency budget, with `provenance.source == "engine"` | IT, OBS (AT-1) |
| 1.11 | `analytical_forecasts` rows carry a real `mape` or an explicit `null`; `null` renders as "not backtested", never 0 | UT (AT-4) |
| 1.12 | A `catalog_version` mismatch on an analytical row is a cache miss that falls through to a live engine call | UT (AT-2) |
| 1.13 | All 10 `discovery` questions answer correctly; **D1 lists all 19 tables and says which are synthetic**; D10 refuses, naming the missing attributes and listing what *is* held | IT, EV |
| 1.14 | Every answer reading a synthetic table carries the synthetic label in `caveats` and sets `data_layer` | UT, IT (V2-SYN-4, SY-1) |
| 1.15 | `scripts/ingest.py` registers a sample CSV folder end to end, proposing join edges for approval rather than auto-approving | IT (`GRD-2`, `GRD-12`) |
| 1.16 | Discovery answers contain no figure that is not a catalog-held count | INS (`SAFE-8`) |
| 1.17 | Zero changes to existing test expectations | `pytest backend/tests` stays green |

---

## 4. Track 2 — Python engines

**Goal.** Give every number-producing V2 intent a registered, tested, pure
engine. **This is where SAFE-8 is kept or lost.**

### Library stack

| Library | Used for | Added to |
| --- | --- | --- |
| `numpy` | already present — robust baselines, intervals | core |
| `pandas` | series and contribution table handling across all engines | core |
| `scipy` | significance tests, correlation with p-values, bootstrap | core |
| `statsmodels` | ETS forecasting, OLS/log-log elasticity with standard errors, DiD | core |
| `scikit-learn` | feature importance for wide-indicator diagnostics, segmentation | core |
| `prophet` | primary forecaster (`ds`/`y`, `make_future_dataframe`, `predict`) | `[forecast]` extra |

**Prophet is an optional extra with a mandatory ETS fallback.** Prophet pulls a
compiled Stan backend, which is a heavy and platform-fragile dependency; the
agent must work without it. `python.forecast` tries Prophet, and falls back to
`statsmodels` ETS when it is not installed, raises, fails to converge, or has
too little history for yearly seasonality (23 monthly periods is under two
cycles, so **on this snapshot the fallback is the normal path**). The method
actually used and the reason for any fallback are always reported
(`contracts.md` TR-8) — a silent method change is how a user ends up trusting a
figure produced differently from how they were told.

Prophet usage is confined to **one adapter module**, so the rest of the engine
is testable without it and a CI run with no Prophet installed still exercises
every code path through ETS.

### Files owned

| File | New? | Purpose |
| --- | --- | --- |
| `backend/src/analysts/forecast.py` | new | `python.forecast` — ETS core |
| `backend/src/analysts/_prophet.py` | new | The **only** module importing Prophet; returns `None` when unavailable |
| `backend/src/analysts/impact.py` | new | `python.impact` |
| `backend/src/analysts/scenario.py` | new | `python.scenario`, incl. elasticity estimation |
| `backend/src/analysts/elasticity.py` | new | Log-log demand fit with standard errors and controls |
| `backend/src/analysts/segment.py` | new | `python.segment` (incl. `rank_actions` for prescriptive) |
| `backend/src/analysts/registry.py` | extend | Register the four; keep the closed mapping closed |
| `backend/src/analysts/harness.py` | extend | Dispatch the four; no new capability |
| `backend/src/analysts/driver.py` | extend | Honour `aggregation` (ratio decomposition); correlation + significance + feature importance over synthetic indicators |
| `backend/src/analysts/scoring.py` | extend | Planted-truth scoring against the E1–E4 manifest |
| `backend/tests/test_an1_forecast.py`, `_impact.py`, `_scenario.py`, `_segment.py`, `_elasticity.py` | new | |

### Engine contracts

Each follows the existing convention exactly: `run(inp: AnalystInput) -> AnalystOutput`,
pure, seeded, no network, no warehouse access, never raises for data problems,
returns `insufficient_evidence` with a reason instead (`ANA-1`, `ANA-4`,
`SAFE-8`).

| Engine | Inputs | Outputs | Bounds the answer when | Refuses only when |
| --- | --- | --- | --- | --- |
| `python.forecast` | one prepared series, `horizon`, `anchor`, `alpha` | `yhat`/`yhat_lower`/`yhat_upper` per period, trend + seasonality components, `trend_detectable`, method, fallback reason, backtest MAPE | horizon exceeds the defensible fraction of history ⇒ **answers the defensible horizon** and names the limit (F9); many series ⇒ **answers top N** and reports the remainder (F10) | history < 12 periods; the metric does not exist |
| `python.impact` | an anomaly or driver output, or two measured totals; a `basis` | impact figure with interval, unit, share of total, the basis named | windows misaligned ⇒ **aligns them and says so** (I10); an upper bound is all the data supports ⇒ labels it an upper bound (I9) | the basis is not a measured quantity |
| `python.scenario` | a fitted forecast / impact / **elasticity** + `ScenarioParam[]` | perturbed path with interval, delta vs. base, the fit perturbed, assumptions | the fit is observational ⇒ **answers with the assumptions and interval stated** (X6) | **no fit is obtainable** because the input does not exist in either layer (X10) |
| `python.elasticity` *(inside scenario)* | `price_history`, `competitor_prices`, realised volume, promo controls | log-log elasticity per category with standard error, CI, R², controls listed, synthetic label | thin per-category data ⇒ pools to a parent grouping and says it pooled | no price variation exists for the target |
| `python.segment` | rows + a mode (`rank_segments` / `rank_actions`) | ranked segments with intervals, or 2–3 `ActionOption`s with assumptions, trade-offs, sensitivity, monitoring, and what would change the ranking | every upstream grade < 2 ⇒ the cheapest information-gathering option (`REC-4`) | no segment data |

**Four rules that are not negotiable.**

- **No engine imports a model client.** Enforced by the existing architecture
  test (`test_an1_architecture.py`), extended to the new modules (`SAFE-8`).
- **`python.scenario` never invents a coefficient.** It perturbs a fit that was
  *estimated from data* and reports which, with its interval and fit quality.
  Elasticity is now in scope because `price_history` and `competitor_prices`
  make it estimable — not because the constraint was relaxed.
- **Every fitted estimate carries its uncertainty and its label.** Elasticity
  answers state: point estimate, confidence interval, R², the controls
  included, that it is **observational not experimental**, and that it is
  **based on synthetic data** (V2-SYN-4). An elasticity without those five is
  an overclaim.
- **Non-additive metrics are not additively decomposed.** `review_score`
  (`mean`) and `aov`/`cancellation_rate` (`ratio`) get a numerator/denominator
  decomposition. `DRV-2` requires contributions to reconcile to the total
  change; forcing a share on a mean violates it silently.

### Diagnostic method over the synthetic indicators

`python.driver` gains a three-stage indicator analysis, each stage carrying the
evidence grade it earns (`EVID-1`) and all ending with the causal-boundary note
(`DRV-9`, `E5`):

| Stage | Method | Library | Grade it can reach |
| --- | --- | --- | --- |
| 1. Contribution | additive decomposition over governed dimensions, reconciling to the total (`DRV-2`) | pandas | 1 — concentration |
| 2. Co-movement | Pearson/Spearman with p-values, at lag 0 and at data-permitted lags, FDR-corrected across candidates | scipy | 2 — co-movement |
| 3. Specificity | difference-in-differences against an unaffected comparison group (`DRV-6`) | statsmodels | 3 — specific to unit |
| 4. Importance | feature importance over a fitted model, when the indicator set is wide | scikit-learn | 2 — association only, **never** promoted to causal |

Stage 4 is explicitly capped at grade 2. Feature importance ranks association in
a fitted model; it is not evidence of mechanism, and labelling it as such is the
single easiest way to produce a confident wrong answer.

### Acceptance criteria

| # | Criterion | Verification |
| --- | --- | --- |
| 2.1 | All four engines are in the closed registry with status `implemented`, metadata, params schema and tests; the registry's self-consistency assertions still pass | UT, INS (`ANA-2`) |
| 2.2 | Architecture test: no module under `analysts/` imports a model client, opens a connection or builds SQL | INS (`SAFE-8`) |
| 2.3 | Every engine has tests for sparse data, zero baseline, empty segments and short history, and returns `insufficient_evidence` rather than a forced answer | UT (`ANA-3`, `ANA-4`) |
| 2.4 | Same input + same seed ⇒ byte-identical output for all four | UT |
| 2.5 | **F9 and F10 answer** — the defensible horizon with its limit named, and top-N with the remainder reported. Neither refuses the class | UT, EV (V2-ANS-1, `ABS-3`) |
| 2.6 | `python.forecast` on `aov` forecasts numerator and denominator (F4); on `review_score` respects the 1–5 bound (F8) | UT |
| 2.7 | **The ETS fallback is exercised with Prophet uninstalled** and produces a valid result with `method == "ets"` and a populated `method_fallback_reason`; the full suite passes in a no-Prophet environment | UT, CI matrix (TR-8) |
| 2.8 | With Prophet installed, a forecast reports `method == "prophet"` and exposes trend and seasonality components | UT |
| 2.9 | **X6 answers**: an elasticity point estimate with CI, R², controls listed, the observational caveat and the synthetic label. All five present or the test fails | UT, EV (V2-SYN-4) |
| 2.10 | X10 refuses, naming the absent input and offering the nearest answerable question | UT (`ABS-1`) |
| 2.11 | `python.driver` on `review_score` and `cancellation_rate` decomposes numerator/denominator; it never emits shares that fail `DRV-2` reconciliation | UT (G4, G9) |
| 2.12 | **E3 is correctly explained**: orders up, AOV down, GMV flat — the engine attributes AOV's fall to discount/mix, not to volume | EV against the manifest |
| 2.13 | **E4's confounder is not misreported**: the freight rise is not named as the driver of the review-score drop | EV against the manifest |
| 2.14 | Feature importance output is capped at evidence grade 2 and never carries causal wording | UT, INS (`EVID-1`, `EVID-4`) |
| 2.15 | `python.segment` in `rank_actions` mode returns 2–3 options with all five `REC-3` fields, and the information-gathering option when grades < 2 | UT (`REC-3`, `REC-4`) |
| 2.16 | Each engine is scored against the E1–E4 manifest and a named module baseline | EV (`ANA-5`, `D4`) |

---

## 5. Track 3 — Understanding and planning

**Goal.** Replace the 7-label router and the flat `if route ==` chain with the
8-intent classifier, the resolver, a validated plan DAG and a step executor.

### Files owned

| File | New? | Purpose |
| --- | --- | --- |
| `backend/src/contracts/v2.py` | new | **Written first, before all tracks** |
| `backend/src/intent.py` | new | `IntentResult` — 3-signal fusion over 8 intents |
| `backend/src/resolver_v2.py` | new | `ResolvedQuestion` — entities, defaults, assumptions |
| `backend/src/planner.py` | new | `Plan` — drafted, then code-validated against the tool registry |
| `backend/src/executor_v2.py` | new | Runs the DAG, emits `ToolResult` per step, enforces budgets |
| `backend/src/tools/registry.py` | new | The closed `ToolName` → handler mapping |
| `backend/src/orchestrator.py` | extend | A V2 path **beside** the V1 path, selected by contract version; V1 untouched |
| `backend/src/service.py` | extend | Assemble `AnswerEnvelopeV2`; emit per-step SSE events |
| `backend/src/evidence/ledger.py` | extend | Accept `ToolResult` from the new engines as claim sources |
| `backend/tests/test_intent.py`, `test_resolver_v2.py`, `test_planner.py`, `test_executor_v2.py`, `test_contracts_v2.py` | new | |

### Work

1. **Intent classifier.** Keeps V1's 3-signal design (`RTE-2`): deterministic
   rules, a keyword/catalog classifier, and a model proposal. **Code decides**;
   disagreement lowers confidence; below 0.70 ⇒ `clarify`. Extended to emit
   *several* scored intents with spans for compound questions.
2. **Resolver.** Produces `ResolvedQuestion`: validates entities against
   registry and catalog allowlists, applies defaults, records every default in
   `assumptions`, and reports `inherited_fields` when Track 4 supplied context.
3. **Planner.** The model may draft a plan; code validates it — DAG shape, depth
   ≤ 5, steps ≤ 8, every tool in the closed `ToolName` union, every params
   object against its tool's schema, `python.scenario` has an upstream fit, SQL
   steps fit the budget. An invalid plan falls back to the highest-value single
   intent and records the omission in `intents_dropped` (`RTE-6`).
4. **Step executor.** Topologically executes the DAG, enforces per-run budgets,
   produces one `ToolResult` per step, and degrades on an optional step's
   failure instead of failing the run. Independent steps may run in parallel
   (`OPS-5`).
5. **Envelope assembly.** `step_results` for every planned step including
   skipped ones; `assumptions` merged from resolver and engines; `next_actions`
   populated for `prescriptive` (closing the hardcoded `()`); `route` still
   populated via the documented lossy mapping so a V1 client keeps working.

### Acceptance criteria

| # | Criterion | Verification |
| --- | --- | --- |
| 3.1 | ✅ **done.** `contracts/v2.py`: every type in `contracts.md`, frozen and `extra="forbid"`, re-exporting V1 types rather than redefining them; the §0.1 namespace assertion holds. 101 tests. Deviations in `contracts.md` §11 | UT |
| 3.2 | Every checkable invariant in `contracts.md` §10.2 has a validator, and a test that its violation is **rejected** | UT |
| 3.3 | Intent accuracy over the 80 `scope.md` examples, reported as a confusion matrix including `discovery` and `clarify` | EV (`RTE-7`) |
| 3.4 | Every compound question in `scope.md` §4 produces a plan covering all its intents, or drops one with a stated reason; `intents_covered + intents_dropped` always equals the accepted intents | UT, EV |
| 3.5 | Planner rejects: a cycle, depth > 5, > 8 steps, an unknown tool, a bad params object, a `scenario` with no upstream fit, a plan over query budget | UT (`RTE-6`) |
| 3.6 | A failed **optional** step degrades the run; a failed **required** step reports partial results and says what is missing | UT, IT |
| 3.7 | Architecture test: `planner.py` cannot construct a tool name not in the registry; no `eval`/`exec`/import-by-string anywhere in the V2 path | INS (`ANA-2`, `B0`) |
| 3.8 | Fact Checker passes on every V2 intent: 100% of narrative numbers match a ledger claim | EV (`EVID-3`, `EVID-4`, `SAFE-3`) |
| 3.9 | **V1 is unchanged.** Every existing test passes untouched; a `contract_version: "1.0.0"` request takes the V1 path | `pytest backend/tests` |
| 3.10 | All 7 hard-gate counts stay zero across the full V2 eval set | EV (`SAFE-1`, `SAFE-2`, `SAFE-3`, `EVAL-4`) |

---

## 6. Track 4 — Context and discovery

**Goal.** Make follow-ups work and make "what data do you have" a first-class
answer rather than a refusal.

### Files owned

| File | New? | Purpose |
| --- | --- | --- |
| `backend/src/context.py` | new | `ContextState` store: per-session, bounded, permission-scoped |
| `backend/src/followup.py` | new | Classify the follow-up shape and build the inheritance patch |
| `backend/src/clarify.py` | new | Build `ClarificationRequest`s with options and defaults; enforce round ≤ 2 |
| `backend/src/service.py` | extend | Read `session_id` (currently stored and ignored); apply a `clarification_of` reply as an option patch |
| `backend/src/resolver_v2.py` | extend | Consume the context patch, populate `inherited_fields` |
| `backend/tests/test_context.py`, `test_followup.py`, `test_clarify.py` | new | |

### Work

1. **Context store.** Append a `ConversationTurn` per run; **keep the last 10**
   per `session_id`; drop on `catalog_version` change; scope by permission
   (`OPS-4`); store `claim_ids` as **references only** (CTX-2).
   **The rewriter reads only the last 3 turns** (`REWRITE_WINDOW = 3`, CTX-1b):
   10 stored keeps claim references resolvable several turns later, while a
   3-turn rewrite window stops a stale filter leaking into a new question.
2. **Follow-up resolution.** Classify into the eight shapes of `scope.md` §6.1,
   build a patch over the prior `ResolvedQuestion`, and **show what was
   inherited** in the answer. A follow-up with no prior turn, or one that is
   genuinely ambiguous even with context (U2, U4, V10), is `clarify` — which is
   the correct answer, not a gap.
3. **Structured clarification.** One question, 2–4 options, a stated default,
   round ≤ 2. A reply naming an option applies that option's `resolves_to` patch
   deterministically — the model does not reinterpret the reply. An unanswered
   round 2 proceeds on the default and records it in `assumptions`.
4. **Discovery intent** wired to Track 1's discovery surface.

### Acceptance criteria

| # | Criterion | Verification |
| --- | --- | --- |
| 4.1 | All 10 follow-ups in `scope.md` §6.2 resolve as specified, **including** U2, U4 and V10 resolving to `clarify` | IT, EV |
| 4.2 | U10's 4-turn chain inherits from the immediately preceding turn, not the first | IT |
| 4.3 | Every inherited field appears in `resolved_question.inherited_fields` **and** in the user-visible answer. A silently inherited filter fails the gate | UT, IT (RQ-2) |
| 4.4 | `claim_ids` are never dereferenced into a prompt; a follow-up needing a prior figure re-reads the ledger or re-runs the engine | INS, UT (CTX-2, `SAFE-3`) |
| 4.5 | A `blocked` turn records `resolved = null` and cannot seed the next turn | UT (CTX-4, `SAFE-4`) |
| 4.6 | Context is dropped on `catalog_version` change; never crosses `session_id` or user | UT (CTX-3, `OPS-4`) |
| 4.6b | 10 turns are stored, but a filter 4 turns old is **not** inherited by the rewriter; a claim 8 turns old is still resolvable by reference | UT (CTX-1, CTX-1b) |
| 4.6c | **"What about SP?" as a follow-up answers** (must-answer #4) | IT, `verify:live` (V2-ANS-2) |
| 4.7 | Clarification: exactly one question, 2–4 options, a valid default, round ≤ 2; a round-3 attempt proceeds on the default instead | UT (CL-1..4) |
| 4.8 | Replying with an option id yields a deterministic resolution — same reply, same `ResolvedQuestion`, no model call | UT (CL-6) |
| 4.9 | All 10 vague questions in `scope.md` §5 resolve or clarify as specified; V3 ("anything unusual?") runs an FDR-corrected multi-series scan and **reports the correction used** | IT, EV (`ANOM-6`) |
| 4.10 | The SSE `clarify` event keeps its V1 field names and stays non-terminal; the existing frontend reply box still works unchanged | IT |

---

## 7. Track 5 — UI/UX and visualization

**Goal.** Render the V2 answer: the plan, the steps, the charts, the
assumptions, and the follow-ups — **without the frontend computing anything.**

### Files owned

All under `frontend/web/src/`. `frontend/web/CLAUDE.md` governs this track in
full and is not superseded by anything here; in particular §0 (no purple), §3b
(the frontend computes nothing) and §4 (accessibility) apply unchanged.

| File | New? | Purpose |
| --- | --- | --- |
| `types/envelope.ts` | extend | Mirror the V2 types; `tuple[X, ...]` → `readonly X[]`, `X \| None` → `X \| null` |
| `components/briefing/PlanView.tsx` | new | The step DAG with per-step status, purpose and duration |
| `components/viz/VizFrame.tsx` | new | Render a `VisualizationSpec` against its referenced `ToolResult` |
| `components/viz/ForecastFan.tsx` | new | Lazy, like the existing `AnomalyChart` |
| `components/briefing/AssumptionsPanel.tsx` | new | Every applied default, visible not buried |
| `components/briefing/FollowUpChips.tsx` | new | Render `follow_ups` verbatim |
| `components/briefing/InheritedScope.tsx` | new | "Carried from your previous question: …" |
| `components/briefing/SyntheticBadge.tsx` | new | The synthetic-data label, driven by `provenance.data_layer` (V2-SYN-4) |
| `components/briefing/FitQuality.tsx` | new | Method, fallback reason, interval and MAPE/R² — `null` renders "not backtested", never 0 |
| `components/ask/ClarifyOptions.tsx` | new | Options as buttons + the default, replacing the free-text-only reply |
| `lib/stages.ts` | extend | Per-step SSE events (`step_results` makes the sparse step ids obsolete) |
| `lib/mock/envelopes.ts` | extend | V2 scenarios for every intent and status |
| `lib/followUps.ts` | **delete the local templating** | The backend now supplies `follow_ups` with `answerable: true` |

### Work

1. **Render specs, do not infer charts.** `VizFrame` reads `kind` and `encoding`
   and draws; it never decides what chart the data deserves. This closes gap 3
   (the anomaly series workaround) and gap 15 (type sniffing) at the source.
2. **`emphasis`, not colour.** The backend sends `normal` / `attention`; the
   frontend maps those onto its own tokens. The no-purple rule stays locally
   enforceable because the backend never names a colour.
3. **Top-N is the backend's.** `encoding.limit` is already applied upstream and
   the remainder is in the caption. The frontend does not slice (VZ-3, §3b).
4. **Follow-ups come from the backend.** `lib/followUps.ts`'s local templating is
   deleted. The frontend renders `follow_ups[]` verbatim and renders nothing
   when it is empty.
5. **Assumptions are prominent.** A forecast anchored on 2018-08 because
   2018-09 has 16 orders is the single most important sentence on that screen.
6. **Clarify becomes clickable.** Options as real buttons; the default stated;
   the free-text box retained as the escape hatch.
7. **`next_actions` renders for real.** Gap 1's "mock mode only" note is
   retired once Track 2's `python.segment` populates it.

### Acceptance criteria

| # | Criterion | Verification |
| --- | --- | --- |
| 5.1 | `npm run typecheck` and `npm run build` clean, no warnings, strict mode unchanged | gate |
| 5.2 | Colour gate: names grep clean, and all tokens across 3 accents × 2 themes outside the forbidden hue band | gate (§0) |
| 5.3 | **Nothing is computed.** An architecture review of every new component against §3b's table; no delta, ratio, total, slice or re-round of a backend figure | INS |
| 5.4 | `npm run verify:features` green: mock scenarios for all 8 intents × all statuses | gate |
| 5.5 | `npm run verify:live` green against the real backend, with the chip set extended to cover `diagnostic` (reachable once V2-PRE-1 lands), `forecast` and `discovery` | gate |
| 5.6 | axe: 0 violations including `minor` and `best-practice`, both themes, on every new surface — charts keyboard-reachable and labelled, `VizFrame`'s scroll container `tabIndex={0}` | gate (§4) |
| 5.7 | A `contract_version: "1.0.0"` envelope renders exactly as it does today | regression |
| 5.8 | A forecast chart **always** shows its interval; a one-point series never renders as a line | UT (VZ-5, VZ-6) |
| 5.9 | `assumptions` and `inherited_fields` are visible without expanding anything | INS, audit screenshots |
| 5.10 | Every `follow_ups` chip, when clicked, returns a non-`clarify` answer | `verify:live` |
| 5.11 | **Every answer reading a synthetic table shows the synthetic badge**, and it is legible in both themes at AA contrast | UT, axe, audit (V2-SYN-4) |
| 5.12 | A forecast shows its method and, on fallback, the reason; a `null` MAPE reads "not backtested" and never 0 | UT (TR-8, AT-4) |
| 5.13 | **All nine must-answer questions reach `answered`** through the real UI | `verify:live` (V2-ANS-2) |

---

## 8. Cross-track gates

Nothing is tagged until all of these hold.

| Gate | Requirement | Owner |
| --- | --- | --- |
| **G1** | All V1 hard gates stay zero across the full V2 eval set: no out-of-allowlist identifier executed, no write/DDL executed, no unsourced numeric claim | `SAFE-1`, `SAFE-2`, `SAFE-3`, `EVAL-4` |
| **G2** | Architecture test: nothing under `analysts/`, `sql/validator.py`, `sql/reconciler.py` or `contracts/` imports a model client | `SAFE-8` |
| **G3** | Faithfulness 100%: every number in every V2 narrative matches a ledger claim | `EVID-3`, `EVID-4` |
| **G4** | Zero causal overclaims: `scenario` and `diagnostic` answers never exceed their evidence grade; the causal-boundary note is present on every driver answer | `EVID-1`, `DRV-9`, `E5` |
| **G5** | **All nine must-answer questions return `answered`.** Over-refusal rate reported and within threshold. Only D10 and X10 refuse, both because an input genuinely does not exist | V2-ANS-2, `ABS-1`, `ABS-3` |
| **G5b** | Every synthetic-derived figure is labelled synthetic, in the envelope and on screen; the real snapshot's checksum is unchanged | V2-SYN-1, V2-SYN-4 |
| **G5c** | Every fitted estimate (forecast, elasticity) reports method, fallback reason, interval and fit quality | TR-8 |
| **G6** | Latency per intent measured and documented, not assumed. Compound intents get their own budget, set from measurement | `OPS-6`, `EVAL-7` |
| **G7** | Thresholds calibrated on the dev set and frozen in `spec/thresholds.md` before any held-out run | `EVAL-7` |
| **G8** | The full suite runs on the tag and results are committed under `eval/results/<tag>/` | `EVAL-5` |
| **G9** | `README.md`, `requirements.md` (new `V2-*` rows) and `Interfaces.md` (a pointer to `spec/v2/contracts.md`) updated. Targets are never reported as results | `DEL-2`, `EVAL-8` |

---

## 9. What is explicitly deferred

| Deferred | Reason |
| --- | --- |
| The `risk` analyst (churn model) | Already specified in V1 (`RISK-1..8`) and still unbuilt. V2 does not pull it forward. |
| Experimental causal identification | No randomisation exists. The elasticity estimate is observational and labelled as such. |
| Cross-session memory | Per-`session_id` only. |
| Learned dialogue management | Context is bounded slot inheritance, not a policy (`A3`). |
| Free-form Python | `ANA-2`, `B0`. Permanent. |
| Autonomous action execution | `REC-5`. Permanent. |

---

## 11. Decisions recorded (approval, 2026-10-30)

The plan was approved with these overrides. Recorded here rather than in a
review checklist, so the rationale survives.

| # | Decision | Effect |
| --- | --- | --- |
| 1 | **Branch `major-project-update`.** | All V2 work, including the Track 0 fixes. |
| 2 | **Track 0 approved.** Fix the driver `TypeError` (V2-PRE-1) in its own commit with a regression test; raise budgets (V2-PRE-2). | This is the one place V1 behaviour changes, deliberately, because it is broken. |
| 3 | **Synthetic data added to Track 1.** Seeded generator → `data/brazil_ecommerce_v2.sqlite`, 19 tables, four planted effects, ground truth in `data/SYNTHETIC_GROUND_TRUTH.md`; plus `scripts/ingest.py` and `semantics/`. | Track 1 roughly doubles in size and becomes the critical path: 5 of 9 must-answer questions depend on it. |
| 4 | **Precomputed anomalies and forecasts** as analytical tables. | S5 ("spikes across all months") becomes one indexed read. New contract §5.1 with AT-1..5. |
| 5 | **Library stack:** pandas, scipy, statsmodels, scikit-learn; **Prophet** primary for forecasting with an **automatic ETS fallback**. | Prophet is an optional extra behind one adapter module; ETS is the normal path on 23 periods of history. Method and fallback reason always reported. |
| 6 | **Price elasticity is in scope**, estimated from `price_history` / `competitor_prices` with stated assumptions, intervals and the synthetic label. | `scope.md` X6 became a must-answer; X10 (Argentina) is now the refusal case. |
| 7 | **V2-ANS-1 — answer with stated assumptions rather than refuse.** F9 and F10 changed from refusals to bounded answers; G10 answers at grade 3 via DiD. | Only D10 and X10 remain refusals: both because an input genuinely does not exist. |
| 8 | **Nine must-answer questions are a hard gate** (V2-ANS-2, `scope.md` §7). | Gate G5; `verify:live` 5.13. |
| 9 | **Eight intents**, `discovery` and `clarify` first-class. | As specified. |
| 10 | **`contract_version: "2.0.0"`** with the documented lossy `route` mapping. | V1 clients keep working. |
| 11 | **Engines:** `forecast`, `impact`, `scenario`, `segment`, plus existing `anomaly` and `driver`. | Six registered engines. |
| 12 | **Budgets raised per intent.** | V2-PRE-2. |
| 13 | **Context: store 10 turns, rewrite from the last 3.** | CTX-1 and the new CTX-1b. |
| 14 | **Track order approved**; Track 5 starts on fixtures in parallel from day one. | As in §2. |

### Implementation order from here

1. ✅ Specs updated.
2. ✅ V2-PRE-1 — driver `TypeError` fixed, 2 regression tests, own commit
   (`db1c4d1`). Verified end to end against the real snapshot.
3. ✅ V2-PRE-2 — per-route budgets via `BudgetPolicy`, 6 tests, own commit
   (`f965c07`).
4. ✅ `backend/src/contracts/v2.py` + 101 tests. Suite at 541 green.
5. **← stopped here for review before Track 1.**

Track 1 is next and is the critical path: the synthetic generator, the
completeness rule, the precomputed analytical tables and the discovery
surface. Five of the nine must-answer questions depend on it.

One thing to settle before Track 1 starts: `.gitignore` currently ignores
`*.sqlite`, so `data/brazil_ecommerce_v2.sqlite` will not be committed. That
is almost certainly right — it is a build artefact of a seeded generator and
should be rebuilt, not stored — but it means `SYNTHETIC_GROUND_TRUTH.md` and
the generator must be committed and the database must not, and CI has to run
the generator before the eval suite.
