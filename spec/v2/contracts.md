# V2 Contracts — Agent Hand-offs

**Location in repo:** `spec/v2/contracts.md`
**Status:** **implemented** in `backend/src/contracts/v2.py`, 101 tests.
Deviations found during implementation are recorded in §11.
**Companions:** [`scope.md`](scope.md), [`build-plan-v2.md`](build-plan-v2.md)
**Inherits conventions from:** [`Interfaces.md`](../Interfaces.md) §1

---

## 0. Conventions and the namespace rule

Everything in `Interfaces.md` §1.1 still applies: UTC ISO-8601 timestamps,
`Period` is start-inclusive/end-exclusive, sensitive columns are masked before
they enter any contract object, producers never round.

Additionally, for V2:

- **Frozen and strict.** Every model extends the existing `ContractModel`
  (`model_config = ConfigDict(frozen=True, extra="forbid")`), so a step cannot
  quietly widen a contract its consumers depend on.
- **Tuples, not lists.** Sequences are `tuple[X, ...]` to keep models hashable
  and immutable, matching V1 (`frontend/web/CLAUDE.md` §8 maps these to
  `readonly X[]`).
- **No floats without provenance.** Any field holding a figure that reaches a
  user carries, or is reachable from, a `source` identifying the SQL query id or
  engine run that produced it. This is the contract-level expression of
  `SAFE-3`/`SAFE-8`.

### 0.1 Name collisions with V1 — read this before writing code

`contracts/models.py` **already defines** `PlanStep`, `Period`,
`ClarificationResult`, `AnalystOutput` and `ToolResult`-adjacent types. The V2
names below deliberately reuse two of those words with different shapes:

| Name | V1 (`contracts/models.py`) | V2 (`contracts/v2.py`) |
| --- | --- | --- |
| `PlanStep` | `step_id`, `module`, `depends_on`, `status`, `detail` — a *trace record* of an executed step | `step_id`, `tool`, `params`, `depends_on`, … — an *instruction* to execute |
| `Plan` | *(not in models.py; only in `Interfaces.md` §3 as TypeScript)* | the executable DAG |

**Rules.**
1. `contracts/v2.py` **re-exports** `Period`, `MetricDefinition`,
   `AnalystOutput`, `ExecutionResult` and `LedgerClaim` from
   `contracts.models` — they are correct as they stand and must not be
   duplicated. (`AnalystOutput` needed one additive widening to name the new
   engines; see §11.1.)
2. `contracts/v2.py` defines `PlanStep` and `Plan` as **new** types. The module
   must never be star-imported alongside `contracts.models`; a test asserts
   `contracts.v2.PlanStep is not contracts.models.PlanStep` so the shadowing is
   deliberate and visible rather than accidental.
3. V1's `PlanStep` keeps its current role as the executed-step trace record in
   `OrchestrationResult.plan`. V2's `Plan` is what the planner *emits*; V1's
   `PlanStep` tuple is what the orchestrator *recorded*. Both appear in a V2
   envelope, which is why they must not be merged.

### 0.2 Producer → consumer map

| # | Producer | Consumer | Contract |
| --- | --- | --- | --- |
| 1 | API / `RunService` | ContextResolver | `ConversationTurn` appended to `ContextState` (§1) |
| 2 | ContextResolver | IntentClassifier | `ResolvedQuestion` (§2) |
| 3 | IntentClassifier | Planner | `IntentResult` (§3) |
| 4 | IntentClassifier / Planner | API → user | `ClarificationRequest` (§4) |
| 5 | Planner | Executor loop | `Plan` of `PlanStep` (§5) |
| 6 | Executor loop | Planner (re-plan) / Ledger | `ToolResult` (§6) |
| 7 | Executor loop | Frontend | `VisualizationSpec` (§7) |
| 8 | Everything | Frontend | `AnswerEnvelopeV2` (§8) |

---

## 1. `ContextState` and `ConversationTurn`

**Purpose.** Make follow-ups resolvable. V1 stores `session_id` and never reads
it (`service.py:147`); `ContextState` is what reading it produces.

**Ownership.** Held server-side per `session_id`, bounded to the last 10 turns,
never shared across users, scoped by permission like the plan cache (`OPS-4`),
and invalidated when `catalog_version` changes.

```ts
interface ConversationTurn {
  turn_id: string;                       // "T1", "T2"
  run_id: string;                        // the run that answered it
  at: string;                            // UTC ISO-8601
  question: string;                      // the raw user text of this turn
  resolved: ResolvedQuestion | null;     // null if the turn never resolved (blocked/refused)
  intent: IntentName | null;
  status: RunStatus;                     // reuses the V1 literal
  claim_ids: string[];                   // "C1".. — numbers this turn produced, BY REFERENCE ONLY
  scope_summary: string;                 // one line, safe to show: "Revenue, 2018, SP"
}

interface ContextState {
  contract_version: string;
  session_id: string;
  catalog_version: string;               // context is void across a catalog change
  turns: ConversationTurn[];             // oldest first, max 10
  pending_clarification: ClarificationRequest | null;   // set when the last turn asked
}
```

**Invariants.**

- **CTX-1.** `turns` holds at most **10** entries; the oldest is dropped first.
- **CTX-1b.** The **question rewriter reads only the last 3 turns.** Storage and
  rewriting windows are deliberately different: 10 turns keep claim references
  resolvable for "what did that add?" several turns later, while the rewriter
  sees 3 so that an old filter cannot silently leak into a new question. The
  rewriter's window is a constant, `REWRITE_WINDOW = 3`, and a test asserts a
  4-turn-old filter is **not** inherited.
- **CTX-2.** `claim_ids` are **references**, never values. A follow-up that
  needs a prior figure re-reads it from that run's ledger or re-runs the engine
  over the stored rows. Copying a number into a prompt and re-emitting it would
  detach it from its evidence and break `SAFE-3`.
- **CTX-3.** `catalog_version` mismatch ⇒ the context is dropped and the
  follow-up is treated as a cold question.
- **CTX-4.** A turn whose `status` is `blocked` records the question but
  `resolved = null`, so an injection attempt cannot seed context for the next
  turn (`SAFE-4`).
- **CTX-5.** `scope_summary` is safe-to-display text, never raw rows or
  sensitive values — the same rule as SSE `summary` (`Interfaces.md` §2.2).

### Example

```json
{
  "contract_version": "2.0.0",
  "session_id": "8f1c2d4e-1b77-4c8a-9d3e-0a51b7c62e40",
  "catalog_version": "olist-2026-10-01",
  "turns": [
    {
      "turn_id": "T1",
      "run_id": "a3f1c9d2e4b54f70a9c81d6b2f3e7a05",
      "at": "2026-10-30T09:14:22Z",
      "question": "What was revenue in 2018?",
      "resolved": {
        "contract_version": "2.0.0",
        "text": "What was revenue in 2018?",
        "metric_id": "revenue",
        "dimensions": [],
        "filters": [],
        "period": { "start": "2018-01-01", "end": "2018-09-01" },
        "comparison_period": null,
        "grain": "month",
        "inherited_fields": [],
        "assumptions": [
          "2018 was read as 2018-01 to 2018-08 inclusive: 2018-09 (16 orders) and 2018-10 (4 orders) are incomplete collection periods."
        ],
        "resolution_source": "deterministic",
        "confidence": 0.93
      },
      "intent": "descriptive",
      "status": "answered",
      "claim_ids": ["C1"],
      "scope_summary": "Revenue, 2018-01 to 2018-08, all states"
    }
  ],
  "pending_clarification": null
}
```

---

## 2. `ResolvedQuestion`

**Purpose.** One object that says exactly what question is being answered, after
context inheritance and after defaults are applied. It is the thing shown back
to the user ("Revenue, 2018, SP — carried from your previous question") and the
thing cached on (`OPS-4`).

```ts
interface ResolvedQuestion {
  contract_version: string;
  text: string;                          // the raw text of THIS turn
  effective_text?: string;               // the rewritten standalone question, when inherited
  metric_id: string | null;              // governed metric id, or null when ungoverned
  ungoverned_metric_term?: string;       // the raw term, when metric_id is null
  dimensions: string[];                  // governed dimension names
  filters: ResolvedFilter[];
  period: Period | null;
  comparison_period: Period | null;
  grain: MetricTimeGrain | null;
  inherited_fields: string[];            // which fields came from context, e.g. ["metric_id","period"]
  assumptions: string[];                 // every default applied, in user-readable words
  resolution_source: "deterministic" | "context" | "model_proposed_code_validated";
  confidence: number;                    // 0..1, decided by code
}

interface ResolvedFilter {
  dimension: string;                     // governed dimension name
  operator: "=" | "!=" | "in" | ">" | ">=" | "<" | "<=";
  values: string[];                      // literals already value-linked and allowlisted
  source_phrase: string;                 // what the user actually typed ("SP")
  link_confidence: number;               // 0..1 from the Value Index (GRD-8)
}
```

**Invariants.**

- **RQ-1.** Every `dimensions` entry and every `filters[].dimension` is checked
  against the metric's `allowed_dimensions` before this object is built. An
  unlisted dimension is a refusal, not a field value (`SAFE-1`, `MET-1`).
- **RQ-2.** `inherited_fields` must be non-empty whenever
  `resolution_source == "context"`, and every inherited field must be shown to
  the user. Silent inheritance is forbidden (scope.md §6.3.2).
- **RQ-3.** Every applied default appears in `assumptions` in plain words,
  including window truncation (V2-DATA-3).
- **RQ-4.** `confidence < 0.70` ⇒ the caller must emit a
  `ClarificationRequest`, not proceed. This mirrors V1's `RouterResult`
  validator (`models.py:596`).
- **RQ-5.** `metric_id == null` ⇒ the answer carries the visible
  `ungoverned_metric` badge (`MET-4`).
- **RQ-6.** `filters[].values` are literals produced by the Value Index, never
  by a model. `link_confidence` below threshold ⇒ clarify (`GRD-8`).

### Example — a follow-up, "What about SP?"

```json
{
  "contract_version": "2.0.0",
  "text": "What about SP?",
  "effective_text": "What was revenue in 2018 for customers in SP?",
  "metric_id": "revenue",
  "ungoverned_metric_term": null,
  "dimensions": [],
  "filters": [
    {
      "dimension": "customer_state",
      "operator": "=",
      "values": ["SP"],
      "source_phrase": "SP",
      "link_confidence": 0.98
    }
  ],
  "period": { "start": "2018-01-01", "end": "2018-09-01" },
  "comparison_period": null,
  "grain": "month",
  "inherited_fields": ["metric_id", "period", "grain"],
  "assumptions": [
    "Metric, window and grain were carried from your previous question (Revenue, 2018-01 to 2018-08).",
    "SP was read as customer_state = 'SP' (41,746 customers), not seller_state."
  ],
  "resolution_source": "context",
  "confidence": 0.91
}
```

---

## 3. `IntentResult`

**Purpose.** Replace V1's 7-value `RouteLabel` with the 8 intents of
`scope.md` §1, carrying the entities each intent needs. A compound question
returns **several** intents and the planner builds a step per intent.

```ts
type IntentName =
  | "discovery" | "clarify" | "descriptive" | "diagnostic"
  | "impact"    | "forecast" | "scenario"   | "prescriptive";

interface IntentResult {
  contract_version: string;
  intents: ScoredIntent[];               // >= 1, ordered: primary first
  entities: Entities;
  signals: IntentSignals;                // kept for the trace and for RTE-2
  confidence: number;                    // 0..1, code's own figure
  reason: string;                        // shown as "Treated as ... because ..."
  clarification: ClarificationRequest | null;
  prd_intent_label: IntentLabel;         // Descriptive|Comparative|Diagnostic|Prescriptive (RTE-5)
}

interface ScoredIntent {
  intent: IntentName;
  score: number;                         // 0..1
  span?: string;                         // the clause that produced it, for compound questions
}

interface Entities {
  metric_id: string | null;
  secondary_metric_ids: string[];        // "revenue and order count"
  dimensions: string[];
  filters: ResolvedFilter[];
  period: Period | null;
  comparison_period: Period | null;
  grain: MetricTimeGrain | null;
  horizon: Horizon | null;               // forecast only
  scenario_params: ScenarioParam[];      // scenario only
  action_intent: boolean;
}

interface Horizon {
  periods: number;                       // >= 1
  grain: MetricTimeGrain;
  anchor: string;                        // the last COMPLETE period, "2018-08" (V2-DATA-2)
}

interface ScenarioParam {
  target: string;                        // governed metric id or dimension name
  kind: "multiplicative" | "additive" | "absolute" | "remove" | "mix_shift";
  value: number;                         // 1.10 for "+10%"
  applies_to?: { dimension: string; values: string[] };
  source_phrase: string;                 // "freight costs rise 10%"
}

interface IntentSignals {
  rules:      { matched: string[]; intents: IntentName[] };
  classifier: { intents: ScoredIntent[] };
  model:      { proposed: IntentName[]; entities: Entities; confidence: number } | null;
  agreement:  boolean;                   // disagreement lowers confidence (RTE-2)
}
```

**Invariants.**

- **IR-1.** `intents` is non-empty and ordered; `intents[0]` is the primary.
- **IR-2.** `clarify` cannot be combined with another intent. `discovery` may be
  (K8: discovery + diagnostic).
- **IR-3.** `confidence < 0.70` ⇒ `intents == ["clarify"]` and
  `clarification != null`. Code decides; the model only proposes (`RTE-2`).
- **IR-4.** `horizon != null` is required for `forecast`, forbidden otherwise.
  `horizon.anchor` must be a complete period (V2-DATA-2).
- **IR-5.** `scenario_params` is non-empty for `scenario`, forbidden otherwise.
- **IR-6.** `scenario` must not be the only intent unless the session already
  holds a fit to perturb; otherwise the planner returns
  `insufficient_evidence` (scope.md X7, X10).
- **IR-7.** Every entity is validated against the catalog and registry
  allowlists before the object is constructed (`SAFE-1`).

### Example — compound, "How does revenue trend look today and what will it be in 3 months?"

```json
{
  "contract_version": "2.0.0",
  "intents": [
    { "intent": "descriptive", "score": 0.94, "span": "how does revenue trend look today" },
    { "intent": "forecast",    "score": 0.91, "span": "what will it be in 3 months" }
  ],
  "entities": {
    "metric_id": "revenue",
    "secondary_metric_ids": [],
    "dimensions": [],
    "filters": [],
    "period": { "start": "2017-09-01", "end": "2018-09-01" },
    "comparison_period": null,
    "grain": "month",
    "horizon": { "periods": 3, "grain": "month", "anchor": "2018-08" },
    "scenario_params": [],
    "action_intent": false
  },
  "signals": {
    "rules": { "matched": ["trend_phrase", "future_window"], "intents": ["descriptive", "forecast"] },
    "classifier": { "intents": [
      { "intent": "descriptive", "score": 0.88 },
      { "intent": "forecast", "score": 0.84 }
    ] },
    "model": {
      "proposed": ["descriptive", "forecast"],
      "entities": { "metric_id": "revenue", "secondary_metric_ids": [], "dimensions": [],
                    "filters": [], "period": null, "comparison_period": null, "grain": "month",
                    "horizon": { "periods": 3, "grain": "month", "anchor": "2018-08" },
                    "scenario_params": [], "action_intent": false },
      "confidence": 0.86
    },
    "agreement": true
  },
  "confidence": 0.92,
  "reason": "Treated as a trend report plus a 3-month forecast, because the question asks both how revenue looks now and what it will be later. The forecast is anchored on 2018-08, the last complete month.",
  "clarification": null,
  "prd_intent_label": "Descriptive"
}
```

---

## 4. `ClarificationRequest`

**Purpose.** One question, 2–4 options, a stated default, bounded to 2 rounds.
V1's `ClarificationResult` carries only two prose strings
(`what_understood`, `what_needs_clarification`) with no options and no default,
so the frontend can only render a free-text reply box. V2 keeps those two fields
(the frontend and the SSE `clarify` event already depend on them) and adds the
structure around them.

```ts
interface ClarificationRequest {
  contract_version: string;
  what_understood: string;               // kept from V1; SSE clarify event field
  what_needs_clarification: string;      // kept from V1; SSE clarify event field
  question: string;                      // the ONE question asked
  options: ClarificationOption[];        // 2..4
  default_assumption: DefaultAssumption; // what happens if the user says nothing
  round: 1 | 2;                          // hard cap
  slot: ClarifiableSlot;                 // which slot is missing
  of_run_id?: string;                    // the run this clarifies (round 2)
}

interface ClarificationOption {
  option_id: string;                     // "O1".."O4"
  label: string;                         // "Last 12 complete months"
  detail?: string;                       // "2017-09 to 2018-08"
  resolves_to: Record<string, unknown>;  // the partial ResolvedQuestion patch this option applies
  recommended: boolean;                  // at most one true
}

interface DefaultAssumption {
  option_id: string;                     // must match an options[] entry
  rationale: string;                     // why this is the safe default
}

type ClarifiableSlot =
  | "metric" | "period" | "comparison_period" | "grain"
  | "dimension" | "filter_value" | "horizon" | "scenario_param" | "intent";
```

**Invariants.**

- **CL-1.** Exactly one question per request. Asking two things at once is the
  behaviour V2 is replacing.
- **CL-2.** `2 <= options.length <= 4`.
- **CL-3.** `default_assumption.option_id` must match an `options[].option_id`.
  There is always a default: round 2 unanswered means the agent proceeds on it
  and records it in `ResolvedQuestion.assumptions` and
  `AnswerEnvelopeV2.assumptions`.
- **CL-4.** `round <= 2`. A third would be required only if round 2's reply
  introduced new ambiguity; in that case the agent proceeds on the default
  instead of asking again (scope.md §3.2).
- **CL-5.** At most one `recommended: true`.
- **CL-6.** `options[].resolves_to` keys must be `ResolvedQuestion` field names,
  validated against its schema. The option is a *patch*, so accepting it is
  deterministic — the model does not re-interpret the reply.
- **CL-7.** A clarification is **HTTP 200** with `status: "clarify"`, not an
  error (`Interfaces.md` §1.2), and the SSE `clarify` event is **not terminal**
  (`frontend/web/CLAUDE.md` §5).

### Example — "Summarize revenue"

```json
{
  "contract_version": "2.0.0",
  "what_understood": "You are asking for a summary of Revenue (metric_id: revenue).",
  "what_needs_clarification": "Which time window should the summary cover?",
  "question": "Which time window should I summarise revenue over?",
  "options": [
    {
      "option_id": "O1",
      "label": "Last 12 complete months",
      "detail": "2017-09 to 2018-08",
      "resolves_to": { "period": { "start": "2017-09-01", "end": "2018-09-01" }, "grain": "month" },
      "recommended": true
    },
    {
      "option_id": "O2",
      "label": "2018 to date",
      "detail": "2018-01 to 2018-08",
      "resolves_to": { "period": { "start": "2018-01-01", "end": "2018-09-01" }, "grain": "month" },
      "recommended": false
    },
    {
      "option_id": "O3",
      "label": "All history",
      "detail": "2016-10 to 2018-08, excluding incomplete edge months",
      "resolves_to": { "period": { "start": "2016-10-01", "end": "2018-09-01" }, "grain": "month" },
      "recommended": false
    }
  ],
  "default_assumption": {
    "option_id": "O1",
    "rationale": "Twelve complete months is the shortest window that covers a full seasonal cycle, and it excludes 2018-09 and 2018-10, which hold 16 and 4 orders and are incomplete."
  },
  "round": 1,
  "slot": "period"
}
```

---

## 5. `Plan` and `PlanStep`

**Purpose.** Replace V1's flat `if route == …` chain with an executable DAG. The
model may draft it; **code validates it** against the tool registry and the
budget before a single step runs (`RTE-6`, `B4`).

```ts
interface Plan {
  contract_version: string;
  plan_id: string;
  steps: PlanStep[];                     // 1..8, topologically sortable
  depth: number;                         // longest dependency chain, capped at 5
  source: "deterministic_template" | "model_drafted_code_validated" | "fallback_single_step";
  intents_covered: IntentName[];         // must equal IntentResult.intents it accepted
  intents_dropped: DroppedIntent[];      // a compound question may be partly refused
  budget: StepBudget;                    // the whole plan's budget
}

interface DroppedIntent {
  intent: IntentName;
  reason: string;                        // shown to the user
}

interface PlanStep {
  step_id: string;                       // "P1".."P8"
  tool: ToolName;
  params: Record<string, unknown>;       // validated against the tool's params schema
  depends_on: string[];                  // step_ids; no cycles
  produces: StepOutputKind;
  optional: boolean;                     // a failed optional step degrades, not fails, the run
  purpose: string;                       // one safe-to-display line for the trace
}

type ToolName =
  | "sql"                // compile+validate+execute a governed or generated query
  | "catalog"            // read the catalog / registry; never touches the warehouse
  | "analytical_table"   // read a prebuilt semantic-layer table (incl. precomputed anomalies/forecasts)
  | PythonEngineName;

type PythonEngineName =
  | "python.anomaly" | "python.driver"   | "python.forecast"
  | "python.impact"  | "python.scenario" | "python.segment";

type StepOutputKind = "rows" | "catalog_facts" | "analyst_output" | "ranked_options";

interface StepBudget {
  max_queries: number;                   // per RUN, not per step
  max_engine_calls: number;
  max_tokens: number;
  max_wall_ms: number;
}
```

**The tool registry is closed.** `ToolName` is an exhaustive literal union.
There is no `tool: "python.custom"`, no code string parameter and no eval path —
a new engine is added by registering a module with its contract, tests and eval
cases (`ANA-2`, `B0`). This is the same closed-registry discipline as
`analysts/registry.py`, extended to the planner.

### 5.1 `analytical_table` — the precomputed engine-output tables

Two of these tables hold **engine output**, not raw measurements, so that
whole-warehouse questions ("what are the spikes across all months?") are one
indexed read instead of a multi-series scan that blows the query and latency
budget (`scope.md` S5).

```ts
// analytical_anomalies — one row per (kpi, date, dimension value) tested
interface AnomalyRow {
  kpi: string;                           // governed metric_id
  date: string;                          // period start, ISO
  grain: MetricTimeGrain;
  dimension: string | null;              // null = the total series
  dimension_value: string | null;
  value: number;                         // actual, from SQL
  expected: number;                      // from python.anomaly
  delta: number;                         // value - expected
  delta_pct: number;
  direction: "spike" | "dip";
  score: number;                         // robust score
  flagged: boolean;                      // survived FDR correction
  correction: string;                    // e.g. "benjamini_hochberg_0.05"
  computed_at: string;
  engine_version: string;
  catalog_version: string;
  is_synthetic: boolean;                 // true when the kpi reads a synthetic table
}

// analytical_forecasts — one row per (kpi, dimension value, horizon period)
interface ForecastRow {
  kpi: string;
  dimension: string | null;
  dimension_value: string | null;
  grain: MetricTimeGrain;
  anchor_period: string;                 // the last COMPLETE period fitted on
  ds: string;                            // the forecast period
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
  model: "prophet" | "ets";              // which actually ran
  model_fallback_reason: string | null;  // why ETS, when model == "ets"
  mape: number | null;                   // backtest error on a held-out tail
  computed_at: string;
  engine_version: string;
  catalog_version: string;
  is_synthetic: boolean;
}
```

**Invariants.**

- **AT-1.** Every row is **engine output under provenance**. A `ToolResult`
  reading these tables sets `provenance.source = "engine"` with the
  `engine_version` from the row — not `"sql"`. The table is a *cache of engine
  output*; reading it must not launder a figure out of its engine attribution
  (`SAFE-3`, `SAFE-8`).
- **AT-2.** Rows are invalidated on `catalog_version` change and rebuilt by a
  scheduled job. A stale row must never be served: a mismatch is a cache miss
  that falls through to a live engine call.
- **AT-3.** `anchor_period` must be a complete period (V2-DATA-2), and no
  `ds` row may exist for a period the completeness rule flags incomplete.
- **AT-4.** `mape` is `null` when the history was too short to hold out a tail.
  A null `mape` must be reported as "not backtested", never shown as 0.
- **AT-5.** `is_synthetic` propagates to `ToolResult.caveats` and to the
  envelope (V2-SYN-4). A figure derived from generated data is always labelled.

### 5.2 Synthetic-layer provenance

`ToolProvenance` (§6) carries two extra fields so the label cannot be lost:

```ts
interface ToolProvenance {
  // ... as in section 6 ...
  data_layer: "real" | "synthetic" | "mixed";
  synthetic_tables: string[];            // the generated tables actually read
}
```

- **SY-1.** `data_layer != "real"` ⇒ the envelope's `caveats` must name the
  synthetic tables used, and the frontend must show a synthetic badge.
- **SY-2.** `data_layer` is computed from the tables actually read, never
  declared by a model.

**Invariants.**

- **PL-1.** `steps` is a DAG: `depends_on` references existing `step_id`s, no
  cycles, topologically sortable. Validated by code before execution.
- **PL-2.** `depth <= 5`; `len(steps) <= 8`. Over either cap ⇒
  `source = "fallback_single_step"` with the omission recorded in
  `intents_dropped` (`RTE-6`).
- **PL-3.** Every `tool` is in `ToolName` and every `params` object validates
  against that tool's params schema. An unknown tool is a hard error; the
  planner cannot invent a step (`B4`).
- **PL-4.** `python.scenario` must depend on a step producing a fit
  (`python.forecast` or `python.impact`). A scenario with no upstream fit is
  rejected at plan-validation time (`IR-6`).
- **PL-5.** `python.*` steps may depend only on `sql` or `analytical_table`
  steps for their data, never on another engine's *rows* — engines consume
  typed tables the orchestrator supplies, exactly as in V1
  (`harness.py`). **No engine opens a connection or generates SQL** (`SAFE-8`).
- **PL-6.** The sum of planned `sql` steps must not exceed
  `budget.max_queries`. Compound questions that cannot fit drop an intent
  explicitly rather than silently truncating (scope.md §4.2).
- **PL-7.** `intents_covered + intents_dropped` must equal the accepted
  `IntentResult.intents`. Nothing vanishes without a stated reason.

### Example — "Why did August 2018 revenue fall, what did it cost, and what should we do?" (K10)

```json
{
  "contract_version": "2.0.0",
  "plan_id": "pl_7c1a",
  "steps": [
    {
      "step_id": "P1",
      "tool": "sql",
      "params": {
        "metric_id": "revenue",
        "grain": "month",
        "period": { "start": "2016-10-01", "end": "2018-09-01" },
        "dimensions": [],
        "filters": []
      },
      "depends_on": [],
      "produces": "rows",
      "optional": false,
      "purpose": "Monthly revenue series through the last complete month."
    },
    {
      "step_id": "P2",
      "tool": "python.anomaly",
      "params": {
        "metric": "revenue",
        "grain": "month",
        "test_window": { "start": "2018-08-01", "end": "2018-09-01" },
        "history_window": { "start": "2016-10-01", "end": "2018-08-01" },
        "alpha": 0.05,
        "min_volume": 30,
        "use_calendar": false
      },
      "depends_on": ["P1"],
      "produces": "analyst_output",
      "optional": false,
      "purpose": "Test whether August 2018 revenue is outside the expected range."
    },
    {
      "step_id": "P3",
      "tool": "sql",
      "params": {
        "metric_id": "revenue",
        "grain": "month",
        "period": { "start": "2018-07-01", "end": "2018-09-01" },
        "dimensions": ["product_category"],
        "filters": []
      },
      "depends_on": [],
      "produces": "rows",
      "optional": false,
      "purpose": "Revenue by category for July and August 2018, for attribution."
    },
    {
      "step_id": "P4",
      "tool": "python.driver",
      "params": {
        "metric": "revenue",
        "current_period": { "start": "2018-08-01", "end": "2018-09-01" },
        "comparison_period": { "start": "2018-07-01", "end": "2018-08-01" },
        "dimensions": ["product_category"],
        "max_dimensions": 5,
        "max_depth": 2,
        "n_bootstrap": 200,
        "alpha": 0.05,
        "aggregation": "sum"
      },
      "depends_on": ["P3"],
      "produces": "analyst_output",
      "optional": false,
      "purpose": "Attribute the July-to-August change across product categories."
    },
    {
      "step_id": "P5",
      "tool": "python.impact",
      "params": {
        "basis": "anomaly_gap",
        "metric": "revenue",
        "unit": "BRL",
        "alpha": 0.05
      },
      "depends_on": ["P2", "P4"],
      "produces": "analyst_output",
      "optional": false,
      "purpose": "Quantify the shortfall against the expected baseline, in BRL."
    },
    {
      "step_id": "P6",
      "tool": "catalog",
      "params": { "lookup": "action_library", "driver_types": ["category_concentration"] },
      "depends_on": ["P4"],
      "produces": "catalog_facts",
      "optional": true,
      "purpose": "Retrieve candidate actions matching the identified driver type."
    },
    {
      "step_id": "P7",
      "tool": "python.segment",
      "params": { "mode": "rank_actions", "capacity_k": 3, "max_options": 3 },
      "depends_on": ["P5", "P6"],
      "produces": "ranked_options",
      "optional": true,
      "purpose": "Rank actions by quantified impact, evidence grade and feasibility."
    }
  ],
  "depth": 4,
  "source": "model_drafted_code_validated",
  "intents_covered": ["diagnostic", "impact", "prescriptive"],
  "intents_dropped": [],
  "budget": { "max_queries": 4, "max_engine_calls": 5, "max_tokens": 8192, "max_wall_ms": 25000 }
}
```

Note that this plan needs more queries than V1's default `max_queries: 3`
(`models.py:984`). Per-intent budgets are a V2 deliverable, not an oversight
(`OPS-2`, `OPS-6`).

**P3 deliberately depends on nothing.** An earlier draft of this example had
it wait on the anomaly step (`depends_on: ["P2"]`), which pushed the longest
dependency chain to 6 and over the depth cap of 5 — the depth validator in
`contracts/v2.py` rejected it. The dependency was never real: the
by-category query does not need the anomaly verdict to be issued, only the
window, which is known at planning time. Removing it brings the plan to depth
4 **and** lets the two queries run in parallel (`OPS-5`). A false dependency
costs latency and depth for nothing, which is exactly what the declared-depth
check is there to surface.

---

## 6. `ToolResult`

**Purpose.** One envelope for every step's output, whatever the tool, carrying
the provenance that makes its numbers citable. This is the object the Evidence
Ledger consumes.

```ts
interface ToolResult {
  contract_version: string;
  step_id: string;                       // the PlanStep it answers
  tool: ToolName;
  status: "ok" | "empty" | "insufficient_evidence" | "refused" | "skipped" | "error";
  produces: StepOutputKind;

  // exactly one payload is set, matching `produces`
  rows?: RowsPayload;                    // tool "sql" | "analytical_table"
  catalog_facts?: CatalogFactsPayload;   // tool "catalog"
  analyst_output?: AnalystOutput;        // tool "python.*" — the V1 type, reused unchanged
  ranked_options?: ActionOption[];       // tool "python.segment" in rank_actions mode

  provenance: ToolProvenance;
  caveats: string[];
  reason?: string;                       // required when status != "ok"
  duration_ms: number;
}

interface RowsPayload {
  query_id: string;                      // links every cell to its query (SAFE-3)
  columns: { name: string; type: string; role: ColumnRole }[];
  rows: unknown[][];                     // inline under the configured cap
  row_count: number;
  truncated: boolean;
  result_ref?: string;                   // artifact reference above the cap
}

interface CatalogFactsPayload {
  catalog_version: string;
  facts: { key: string; value: unknown; source: string }[];   // source = catalog object id
}

interface ToolProvenance {
  source: "sql" | "engine" | "catalog";
  query_ids: string[];                   // every query that fed this result
  engine?: EngineProvenance;
  input_step_ids: string[];              // which steps' outputs were consumed
  deterministic: boolean;                // same inputs + seed ⇒ same output
  data_layer: "real" | "synthetic" | "mixed";   // computed from tables read (SY-2)
  synthetic_tables: string[];
}

interface EngineProvenance {
  name: PythonEngineName;
  version: string;
  seed: number | null;
  method: string;                        // "prophet", "ets", "ols_loglog", "bh_fdr"
  method_fallback_reason?: string;       // why the fallback ran
  library?: string;                      // "prophet 1.1.5", "statsmodels 0.14.2"
  fit_quality?: FitQuality;              // set whenever a model was fitted
}

interface FitQuality {
  measure: "mape" | "r_squared" | "rmse";
  value: number | null;                  // null = not backtested; never render as 0
  n_observations: number;
  holdout?: Period;
}
```

**Invariants.**

- **TR-1.** Exactly one payload field is set, and it matches `produces`.
- **TR-2.** `status != "ok"` ⇒ `reason` is present. An engine returns
  `insufficient_evidence` with a reason rather than raising (`ANA-4`).
- **TR-3.** `provenance.source` is never `"model"`. **There is no model payload
  variant.** A model cannot produce a `ToolResult`, which is the type-level
  enforcement of `SAFE-8`.
- **TR-4.** Every figure a user eventually sees must be reachable from a
  `ToolResult` through `provenance.query_ids` or
  `provenance.engine` (`SAFE-3`). Enforced by the Fact Checker (`EVID-4`).
- **TR-5.** `deterministic` must be `true` for `sql`, `catalog` and
  `analytical_table`, and for any engine given a `seed`. Bootstrap engines
  without a seed must set it `false` and say so in `caveats`.
- **TR-8.** Whenever a model was fitted, `engine.method` names it and
  `engine.fit_quality` is populated. A forecast whose `model` is `"ets"` must
  carry `method_fallback_reason`. An unreported fallback is a silent change of
  method, which is how a user ends up trusting a number produced differently
  from how they were told.
- **TR-6.** `status == "empty"` is distinct from `"insufficient_evidence"`: a
  true zero-row result is a finding, not a failure (`SQL-12`).
- **TR-7.** Row payloads are masked before construction (`SAFE-5`).

### Example — the forecast step of K1

```json
{
  "contract_version": "2.0.0",
  "step_id": "P2",
  "tool": "python.forecast",
  "status": "ok",
  "produces": "analyst_output",
  "analyst_output": {
    "module": "forecast",
    "status": "ok",
    "parameters": {
      "metric": "revenue",
      "grain": "month",
      "horizon": 3,
      "anchor": "2018-08",
      "method": "ets",
      "alpha": 0.05,
      "history_periods": 23
    },
    "assumptions": [
      "Fitted on 2016-10 through 2018-08. 2018-09 and 2018-10 were excluded as incomplete (16 and 4 orders).",
      "Prophet requires at least two full seasonal cycles to estimate yearly seasonality; 23 monthly periods is under that, so an ETS model with a damped trend was used instead.",
      "The interval is a prediction interval from residual spread, not a confidence interval on the trend."
    ],
    "sources": ["Q1"],
    "artifacts": [
      { "artifact_id": "af_5d2e", "kind": "chart_data", "uri": "/api/artifacts/af_5d2e" }
    ],
    "reason": null,
    "result": {
      "anchor_period": "2018-08",
      "points": [
        { "ds": "2018-09", "yhat": 1053182.44, "yhat_lower": 862405.10, "yhat_upper": 1243959.78 },
        { "ds": "2018-10", "yhat": 1061947.91, "yhat_lower": 812663.52, "yhat_upper": 1311232.30 },
        { "ds": "2018-11", "yhat": 1070713.38, "yhat_lower": 773218.07, "yhat_upper": 1368208.69 }
      ],
      "components": { "trend": "increasing_damped", "seasonality": null },
      "trend_per_period": 8765.47,
      "trend_interval": { "lower": -14203.88, "upper": 31734.82 },
      "trend_detectable": false
    }
  },
  "provenance": {
    "source": "engine",
    "query_ids": ["Q1"],
    "engine": {
      "name": "python.forecast",
      "version": "2.0.0",
      "seed": 0,
      "method": "ets",
      "method_fallback_reason": "Prophet needs >= 24 monthly periods for yearly seasonality; 23 available.",
      "library": "statsmodels 0.14.2",
      "fit_quality": { "measure": "mape", "value": 0.118, "n_observations": 23, "holdout": { "start": "2018-05-01", "end": "2018-09-01" } }
    },
    "input_step_ids": ["P1"],
    "deterministic": true,
    "data_layer": "real",
    "synthetic_tables": []
  },
  "caveats": [
    "The trend interval spans zero, so no trend is statistically detectable: the central path should be read as a level projection, not as growth.",
    "The interval widens from +-18% to +-28% across the three periods.",
    "Backtest error on the held-out tail was 11.8% (MAPE)."
  ],
  "duration_ms": 41
}
```

`trend_detectable: false` with a caveat saying so is the engine refusing to let
prose claim growth that the interval does not support — scope.md F6, enforced
in data rather than in the narrative.

---

## 7. `VisualizationSpec`

**Purpose.** Let the backend say what chart to draw **without sending a figure
the frontend could re-derive**. The frontend computes nothing
(`frontend/web/CLAUDE.md` §3b), and V1 forces it to guess the chart from the
evidence shape (gap 3). A spec references data **by step and column**, never by
inline values.

```ts
interface VisualizationSpec {
  contract_version: string;
  viz_id: string;
  kind: VizKind;
  title: string;
  source_step_id: string;                // the ToolResult holding the data
  source_ref: { query_id?: string; artifact_id?: string };
  encoding: VizEncoding;
  annotations: VizAnnotation[];
  caption: string;                       // what the reader should take from it
  claim_ids: string[];                   // the claims this chart evidences
}

type VizKind =
  | "line" | "bar" | "grouped_bar" | "waterfall"
  | "range_band" | "forecast_fan" | "scatter" | "table";

interface VizEncoding {
  x: { column: string; role: "time" | "dimension"; label: string };
  y: { column: string; role: "measure"; label: string; unit?: string; zero_baseline: boolean };
  series?: { column: string; label: string };     // what splits the series
  band?: { lower_column: string; upper_column: string; label: string };
  sort?: { column: string; direction: "asc" | "desc" };
  limit?: number;                                  // top-N, applied by the BACKEND
}

interface VizAnnotation {
  kind: "point" | "band" | "line" | "label";
  at: { x?: string; x_start?: string; x_end?: string; y?: number };
  label: string;
  emphasis: "normal" | "attention";               // never a colour name
  claim_id?: string;
}
```

**Invariants.**

- **VZ-1.** `encoding` names **columns**, never values. A spec carries no data
  array; the data is the referenced `ToolResult`.
- **VZ-2.** `annotations[].at.y`, when present, must equal a figure the
  referenced `ToolResult` already holds, and `claim_id` must point at a ledger
  claim. An annotation is not a place to introduce a number.
- **VZ-3.** `limit` (top-N) is applied **by the backend**, which re-reports the
  excluded remainder in `caption`. A frontend that hid rows would be computing a
  "top 5" of its own.
- **VZ-4.** `emphasis` is semantic, never a colour. The frontend's palette rules
  are its own (`frontend/web/CLAUDE.md` §0) and the backend must not name
  colours — that is also what keeps the no-purple rule enforceable.
- **VZ-5.** `kind: "forecast_fan"` requires `encoding.band`. A forecast drawn
  without its interval is a misrepresentation.
- **VZ-6.** A single-point series must not be `kind: "line"`
  (`frontend/web/CLAUDE.md` gap 3: "never draw a one-point line chart") — use
  `range_band`.
- **VZ-7.** `zero_baseline` is explicit, because a truncated y-axis on a bar
  chart overstates a change. Default `true` for bars.

### Example — the forecast fan for K1

```json
{
  "contract_version": "2.0.0",
  "viz_id": "vz_1",
  "kind": "forecast_fan",
  "title": "Monthly revenue, actual and 3-month projection",
  "source_step_id": "P2",
  "source_ref": { "query_id": "Q1", "artifact_id": "af_5d2e" },
  "encoding": {
    "x": { "column": "period", "role": "time", "label": "Month" },
    "y": { "column": "value", "role": "measure", "label": "Revenue", "unit": "BRL", "zero_baseline": true },
    "band": { "lower_column": "lower", "upper_column": "upper", "label": "95% prediction interval" }
  },
  "annotations": [
    {
      "kind": "line",
      "at": { "x": "2018-08" },
      "label": "Last complete month",
      "emphasis": "attention"
    },
    {
      "kind": "band",
      "at": { "x_start": "2018-09", "x_end": "2018-11" },
      "label": "Projected",
      "emphasis": "normal"
    }
  ],
  "caption": "Revenue is projected to hold near its 2018 level for three months. The interval spans zero trend, so this is a level projection, not growth. 2018-09 and 2018-10 actuals are excluded as incomplete.",
  "claim_ids": ["C4", "C5"]
}
```

---

## 8. Additions to `AnswerEnvelope`

**Purpose.** Carry the V2 work product. Every V1 field is kept with its current
meaning so the existing frontend keeps working; V2 adds seven fields.

```ts
interface AnswerEnvelopeV2 extends AnswerEnvelope {
  contract_version: "2.0.0";

  // --- new in V2 ---
  resolved_question: ResolvedQuestion | null;   // what was actually answered
  intent: IntentResult | null;                  // the 8-intent classification
  plan: Plan | null;                            // the DAG that was planned
  step_results: StepResultSummary[];            // one per planned step, in plan order
  visualizations: VisualizationSpec[];          // what to draw
  assumptions: string[];                        // every default applied, user-readable
  follow_ups: FollowUpSuggestion[];             // what to ask next

  // --- V1 fields, unchanged in meaning ---
  // run_id, status, route, conclusion, scope, evidence, claims, method,
  // queries, caveats, causal_boundary_note, next_actions, clarification,
  // refusal, block, run_metrics, provenance
}

interface StepResultSummary {
  step_id: string;
  tool: ToolName;
  status: ToolResult["status"];
  purpose: string;                       // from the PlanStep
  summary: string;                       // one safe-to-display sentence
  claim_ids: string[];                   // what this step contributed to the ledger
  duration_ms: number;
  reason?: string;                       // why it was skipped, refused or insufficient
}

interface FollowUpSuggestion {
  text: string;                          // the exact question to ask
  intent: IntentName;
  rationale: string;                     // why it follows
  answerable: true;                      // only ever offered when the backend can answer it
}
```

**Invariants.**

- **EN-1.** `clarification` is the V2 `ClarificationRequest` when
  `status == "clarify"`. The two V1 prose fields are retained inside it, so the
  SSE `clarify` event and the existing reply box are unaffected.
- **EN-2.** `step_results` has exactly one entry per `plan.steps` entry, in plan
  order, including skipped ones with a reason. A step that ran and is not
  reported is a reporting failure, not an optimisation (`EVID-7`).
- **EN-3.** Every number in `conclusion` matches a `claims[].numbers[].token`
  (`EVID-3`, `EVID-4`) — unchanged from V1 and enforced by the existing Fact
  Checker. V2 widens the ledger's sources, not the checker's tolerance.
- **EN-4.** `assumptions` must include everything in
  `resolved_question.assumptions` plus every engine assumption from
  `step_results`. An assumption the user cannot see is a trap.
- **EN-5.** `follow_ups[].answerable` is `true` by construction: a suggestion is
  only emitted after the backend has verified it resolves to a plannable intent.
  This is the backend half of the frontend's existing rule — "returns nothing
  rather than offer a question the backend cannot answer"
  (`frontend/web/CLAUDE.md` §3b).
- **EN-6.** `next_actions` stays the `prescriptive` output and stays empty for
  every other intent (closing gap 1, which is currently hardcoded `()`).
- **EN-7.** `visualizations` may be empty. A single figure is not a chart.
- **EN-8.** `contract_version` is `"2.0.0"`. The frontend keys its parsing on it
  and must keep rendering a `"1.0.0"` envelope unchanged.

### Example — the V2 additions for K1 (V1 fields elided)

```json
{
  "contract_version": "2.0.0",
  "run_id": "b7e2d4a1c9f84e3b85d072fa16c3e9d4",
  "status": "answered",
  "resolved_question": {
    "contract_version": "2.0.0",
    "text": "How does revenue trend look today and what will it be in 3 months?",
    "metric_id": "revenue",
    "dimensions": [],
    "filters": [],
    "period": { "start": "2017-09-01", "end": "2018-09-01" },
    "comparison_period": null,
    "grain": "month",
    "inherited_fields": [],
    "assumptions": [
      "\"Today\" was read as the last complete month, 2018-08.",
      "\"3 months\" was read as the three months after 2018-08.",
      "2018-09 and 2018-10 were excluded from both the trend and the fit: they hold 16 and 4 orders and are incomplete."
    ],
    "resolution_source": "deterministic",
    "confidence": 0.92
  },
  "intent": { "...": "see section 3" },
  "plan": { "...": "P1 sql -> P2 python.forecast" },
  "step_results": [
    {
      "step_id": "P1",
      "tool": "sql",
      "status": "ok",
      "purpose": "Monthly revenue series through the last complete month.",
      "summary": "Returned 23 monthly revenue totals from 2016-10 to 2018-08.",
      "claim_ids": ["C1", "C2", "C3"],
      "duration_ms": 184
    },
    {
      "step_id": "P2",
      "tool": "python.forecast",
      "status": "ok",
      "purpose": "Project revenue three months beyond the last complete month.",
      "summary": "Projected three months with a 95% prediction interval; no trend was statistically detectable.",
      "claim_ids": ["C4", "C5"],
      "duration_ms": 41
    }
  ],
  "visualizations": [ { "...": "see section 7" } ],
  "assumptions": [
    "\"Today\" was read as the last complete month, 2018-08.",
    "\"3 months\" was read as the three months after 2018-08.",
    "2018-09 and 2018-10 were excluded from both the trend and the fit: they hold 16 and 4 orders and are incomplete.",
    "Seasonal period 12 could not be estimated from 23 months of history; a damped trend with a robust level was used instead.",
    "The interval is a prediction interval from residual spread, not a confidence interval on the trend."
  ],
  "follow_ups": [
    {
      "text": "Why did revenue fall in August 2018?",
      "intent": "diagnostic",
      "rationale": "August is the last complete month and the anchor of the projection.",
      "answerable": true
    },
    {
      "text": "What if freight costs rise 10%?",
      "intent": "scenario",
      "rationale": "A fitted forecast is available to perturb.",
      "answerable": true
    },
    {
      "text": "Forecast revenue for SP over the next 3 months",
      "intent": "forecast",
      "rationale": "SP is 42% of customers, so its own projection is meaningful.",
      "answerable": true
    }
  ],
  "caveats": [
    "The trend interval spans zero, so no trend is statistically detectable.",
    "2018-09 and 2018-10 are incomplete collection periods and were excluded."
  ]
}
```

---

## 9. Versioning and migration

- **`contract_version: "2.0.0"`.** Breaking, because `IntentName` replaces
  `RouteLabel` as the primary classification.
- **`route` is retained and populated** on every V2 envelope by mapping
  `IntentName → RouteLabel` (`descriptive|discovery → lookup`,
  `diagnostic → anomaly/driver`, `forecast|scenario|impact|prescriptive → risk`
  as the nearest V1 label), so a V1 client is not broken by a V2 run. The
  mapping is lossy and documented as such; `intent` is the authoritative field.
- **Additive for the frontend.** Every new field is nullable or empty-able, so
  the existing app renders a V2 envelope without changes and gains features as
  it reads the new fields.
- **Schemas and fixtures.** Per `Interfaces.md` §9–10, each type above ships a
  JSON Schema under `contracts/schemas/v2/` and a real instance under
  `contracts/examples/v2/`, and a contract test asserts every fixture validates
  and every producer's test output validates.

---

## 10. Acceptance for this document

`contracts.md` is accepted when `backend/src/contracts/v2.py` exists with:

1. Every type above as a frozen, `extra="forbid"` Pydantic v2 model, re-exporting
   `Period`, `MetricDefinition`, `AnalystOutput`, `ExecutionResult`,
   `LedgerClaim`, `ActionOption`, `ColumnRole`, `MetricTimeGrain`, `IntentLabel`
   and `RunStatus` from `contracts.models` rather than redefining them.
2. A `model_validator` for every numbered invariant that is checkable within one
   object: CTX-1/2/4, RQ-1..6, IR-1..7, CL-1..6, PL-1/2/4/6/7, AT-1/3/4,
   SY-1, TR-1/2/5/6/8, VZ-1/2/5/6, EN-1/2/4/5/7/8. Cross-object invariants
   (TR-3, TR-4, AT-2, SY-2, EN-3) are architecture and Fact Checker tests, not
   field validators.
3. Tests covering: each example JSON in this file parsing and round-tripping;
   every invariant's violation being **rejected**; the namespace assertion of
   §0.1; and an architecture test that `contracts/v2.py` imports no model
   client (`SAFE-8`).
4. Zero changes to any existing test. One **additive** change to
   `contracts/models.py` was unavoidable — see §11.1.

---

## 11. Implementation notes and deviations

Recorded during implementation so the spec and the code do not drift.

### 11.1 `AnalystOutput.module` had to be widened (additive)

§0.1 said `contracts/v2.py` would re-export `AnalystOutput` unchanged. That is
not possible as written: V1 declares

```python
module: Literal["anomaly", "driver", "risk"]
```

so an `AnalystOutput` **cannot name** `forecast`, `impact`, `scenario` or
`segment`. Since `ToolResult.analyst_output` is the only channel an engine
result travels through, a literal that cannot name an engine cannot carry its
result, and the contract would have been unimplementable.

Resolution: a shared `AnalystModuleName` literal in `contracts/models.py`,
used by `AnalystInput`, `AnalystOutput` and `EvidenceBlock`. **Widening a
literal is additive** — every existing value stays valid, and all 440
pre-existing tests pass untouched.

### 11.2 Per-engine result payloads are deferred to Track 2

`AnalystOutput` requires a typed `result` when its status is `ok`, and the
union is currently `AnomalyResult | DriverResult`. The result shapes for the
four new engines (`ForecastResult` and friends) are **Track 2 deliverables**,
to be defined alongside the engines that produce them together with their
params schemas and planted-truth scoring. Pinning their shape here would be
speculative, so `contracts/v2.py` does not define them and the contract tests
exercise the `ToolResult` envelope using an existing typed result. The
`AnalystOutput.result` union widens in Track 2.

### 11.3 One invariant added beyond the spec

**TR-9.** An engine step's `ToolResult` must carry *that* engine's output:
`tool = "python.driver"` with a `forecast` output is rejected. Mislabelling one
engine's result as another's would misattribute every figure in it, and the
check is free.

### 11.4 The K10 example was wrong, and the validator caught it

The flagship plan in §5 originally had `P3` (the by-category query) depend on
`P2` (the anomaly step), giving a longest dependency chain of **6** against a
cap of 5 — so the plan the spec held up as the V2 target could not have been
built. The dependency was never real: that query needs only the window, known
at planning time. Removing it brings the plan to depth 4 and lets the two
queries run in parallel (`OPS-5`). The example and `"depth"` are corrected
above.

This is the declared-depth check (PL-2) doing its job: it exists precisely so
a plan cannot understate its own shape.
