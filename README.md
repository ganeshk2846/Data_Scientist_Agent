# Data Scientist Agent (`DS-AGENT-CORE`)
### Enterprise Decision Intelligence & High-Performance Schema-Grounded NL2SQL Engine

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Pydantic v2](https://img.shields.io/badge/contracts-pydantic--v2-green.svg)](https://docs.pydantic.dev/)
[![SQLGlot](https://img.shields.io/badge/parser-sqlglot-orange.svg)](https://github.com/tobymao/sqlglot)
[![Tests Passing](https://img.shields.io/badge/tests-229%20passing-brightgreen.svg)](backend/tests/)
[![Security Invariants](https://img.shields.io/badge/security-read--only%20enforced-red.svg)](spec/requirements.md)

---

## 1. Overview & Problem Statement

Business teams sit on massive data warehouses but need answers to complex diagnostic questions that simple table lookups cannot answer:
* *"Why did revenue drop in August?"*
* *"What is driving shipping delays across regions?"*
* *"Which accounts have elevated churn risk next quarter?"*

Generic text-to-SQL wrappers (such as single-prompt LLMs or monolithic agent frameworks) fail in the enterprise because they:
1. **Hallucinate schemas:** Invent tables and columns on wide, realistic databases.
2. **Fabricate numbers:** Attempt to perform mental arithmetic or statistical math in text tokens.
3. **Lack security boundaries:** Allow dangerous SQL operations or unindexed full-table scans.
4. **Cannot diagnose:** Return flat rows instead of statistical root causes, decomposition, or recommendations.

**`DS-AGENT-CORE`** is an enterprise-grade Data Scientist Agent. It bridges the gap between raw natural language query translation and rigorous data science analytics through a **Dual-Engine DAG architecture**:

```
                       ┌────────────────────────────────────────────────────────┐
                       │                   USER QUESTION                        │
                       └──────────────────────────┬─────────────────────────────┘
                                                  │
                                       ┌──────────▼──────────┐
                                       │ 1. Ingress Guard    │ (SAFE-4: Prompt Injection & DML Blocker)
                                       └──────────┬──────────┘
                                                  │
                                       ┌──────────▼──────────┐
                                       │ 2. 3-Signal Router  │ (Lookup vs. Anomaly vs. Driver vs. Churn)
                                       └─────┬─────────┬─────┘
                                             │         │
                     ┌───────────────────────┘         └────────────────────────┐
                     ▼                                                          ▼
        [ GOVERNED KPI FAST-PATH ]                                 [ EXPLORATORY NL2SQL ]
        Registry -> Jinja2 -> SQLGlot AST                          Perceptor -> Generator -> Bounded Repair
        (Zero LLM; millisecond compile)                            (Fuzzy Linking + Deterministic Repair)
                     │                                                          │
                     └───────────────────────┬──────────────────────────────────┘
                                             │
                                  ┌──────────▼──────────┐
                                  │ 3. AST Validator    │ (SAFE-1/2: Table Allowlist, Read-Only, AST Cost)
                                  └──────────┬──────────┘
                                             │
                                  ┌──────────▼──────────┐
                                  │ 4. Read-Only Gateway│ (Multi-DB Pool: SQLite, MySQL, PostgreSQL)
                                  └──────────┬──────────┘
                                             │
                                  ┌──────────▼──────────┐
                                  │ 5. Data Reconciler  │ (Grain verification, Null spikes, Fan-out checks)
                                  └──────────┬──────────┘
                                             │
                                  ┌──────────▼──────────┐
                                  │ 6. Analytics Engine │ (Robust Anomaly, Change-Point, Driver Attribution)
                                  └──────────┬──────────┘
                                             │
                                  ┌──────────▼──────────┐
                                  │ 7. Evidence Ledger  │ (Claims linked to SQL rows + regex/causal fact checking)
                                  └──────────┬──────────┘
                                             │
                                  ┌──────────▼──────────┐
                                  │ 8. Executive Answer │ (Narrative Summary + Tables + Visualizations)
                                  └─────────────────────┘
```

> **Core System Invariant (`SAFE-8`):** *"A language model may choose, draft, and explain; it never computes a number, never decides query safety, and never bypasses semantic governance."*

---

## 2. Key Architectural Features

### 🛡️ Deterministic Safety Boundary (`SAFE-1`, `SAFE-2`, `SQL-17`)
* **100% Deterministic Code:** Security gates are enforced purely via AST parsing (`sqlglot`) and regex token heuristics—zero reliance on probabilistic LLMs.
* **Strict Read-Only Guarantee:** Read-only access is enforced at the driver/session level (`?mode=ro` in SQLite; read-only transactions in Postgres/MySQL). Any write attempt (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`) is killed before execution.
* **Dual-Mode Toggle (`SQL-17`):**
  * **Enterprise Mode:** Rejects `SELECT *`, enforces explicit column projections, bounds results with mandatory `LIMIT`, and gates query complexity.
  * **Benchmark Mode:** Relaxes enterprise row truncation to allow exact ground-truth execution matches (`EX >= 70%`) on benchmarks like **BIRD**.

### ⚡ Deterministic Metric Compiler (Zero-LLM Fast-Path)
* Standard business metrics (e.g., GMV, Revenue, Order Count, AOV) bypass the LLM entirely.
* Resolves simple governed questions from a synonym registry, compiles pre-vetted join paths with strict Jinja2 templates, and validates every candidate through the SQLGlot AST. Compilation runs in single-digit milliseconds; warehouse execution time depends on the datasource.
* Fail-closed on unknown metrics or dimensions: the compiler never invents tables, columns or join paths.

### 🔎 Post-Execution Reconciler
* Verifies expected grain, duplicate rows and join fan-out, mandatory-column nulls, numeric ranges, and governed registry totals with an explicit tolerance.
* Surfaces every flag as a user-visible caveat; only flagged results can request a concise diagnosis from the local model.

### 🧠 Native 4-Stage NL2SQL Engine
* **Schema Perceptor:** Deterministic exact/fuzzy value linking, resolving informal user terms (e.g., `"SP"` $\to$ `'customer_state = SP'`) before generation, with low-confidence and ambiguity clarification.
* **Generator:** Deterministic skeleton-of-thought CTE generation using catalog-inferred join paths and frozen table/column allowlists.
* **Bounded Reflector (Self-Repair):** Automatically heals execution and syntax errors from error logs. Strictly capped at **2 attempts** with a **frozen schema allowlist** to prevent runaway loops or scope creep.

### 📊 Pure-Python Statistical Analytics (AN-1)
* **Anomaly Detection:** NumPy-only robust trailing median/MAD baseline, with month-of-year seasonal medians when at least two years of history exist, plus a PELT-style two-segment persistence check.
* **Driver Analysis:** Exact additive contribution by dimension with reconciliation error, approximate intervals and an explicit causal-boundary note.
* **Orchestration:** Router, governed SQL, and analyst DAG with per-run query, token, and wall-time budgets; weak evidence returns `insufficient_evidence` rather than a fabricated conclusion.
* **Evidence Ledger:** Every query row and analyst output becomes a numbered `C1...` claim; the fact checker strips narrative sentences containing unapproved numbers or unsupported causal wording.

---

## 3. Project Structure

```text
Data_Scientist_Agent/
├── backend/                        # Core Python backend engine
│   ├── pyproject.toml              # Project metadata & dependencies
│   ├── src/
│   │   ├── contracts/              # Frozen Pydantic v2 data models (spec/Interfaces.md)
│   │   ├── gateway/                # Multi-database read-only connection & executor
│   │   ├── guard.py                # Ingress security & injection filter
│   │   ├── sql/                    # AST validator, metric compiler, generator, repairer, reconciler
│   │   ├── schema_retriever/       # Fuzzy value linking & schema perception
│   │   ├── catalog/                # Governed metric registry & intent/slot resolver
│   │   ├── models/                 # Local Ollama OpenAI-compatible reasoning client
│   │   ├── analysts/               # Robust anomaly, driver attribution, typed harness
│   │   ├── evidence/               # Numbered claims and deterministic fact checking
│   │   ├── router.py               # 3-Signal intent classifier & router
│   │   ├── orchestrator.py         # Router-to-analyst DAG with execution budgets
│   │   ├── service.py              # Background runs, SSE event store, AnswerEnvelope assembly
│   │   └── app.py                  # FastAPI ask/run/event endpoints
│   └── tests/                      # TDD test suites (229 unit & integration tests)
│
├── frontend/                       # Web UI client & executive dashboard
├── spec/                           # Master engineering specifications & contracts
│   ├── requirements.md             # Traceable requirements matrix (SAFE, SQL, EVAL)
│   ├── Interfaces.md               # API contracts & TypeScript type definitions
│   └── build-plan.md               # 6-Stage prototype execution plan
│
├── docs/                           # Architecture blueprints & documentation
│   ├── DESIGN_DETAIL.md            # Comprehensive system design & mermaid DAGs
│   └── Product.md                  # PRD, user journeys & evaluation targets
│
├── scripts/                        # Database builders & utilities
│   ├── build_brazil_ecommerce_sqlite.py
│   └── strip_database.py
│
├── brazil_ecommerce.sqlite         # Raw analytical database (100K real orders)
└── .gitignore                      # Git protection rules
```

---

## 4. Tech Stack

| Domain | Technologies |
| :--- | :--- |
| **Language** | Python 3.11+ |
| **Type Contracts** | Pydantic v2 (Strict, frozen models) |
| **SQL Engine & Safety** | Jinja2 (strict metric templates), SQLGlot (AST parsing), SQLAlchemy 2.0 (Read-only pooling) |
| **Local LLM Inference** | Ollama (`deepseek-r1:7b`) via standard OpenAI-compatible API |
| **Analytics & Math** | NumPy (robust baselines, intervals, change-point check) |
| **Web & Streaming** | FastAPI, Uvicorn, Server-Sent Events (`StreamingResponse`, buffered replay via `Last-Event-ID`) |
| **CLI & Testing** | Pytest, Rich, Tabulate |

---

## 5. Getting Started

### Prerequisites
* Python 3.11 or higher
* [Ollama](https://ollama.ai) (optional; governed questions run without it. For complex metric mapping and reconciliation diagnosis: `ollama pull deepseek-r1:7b`)

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/ganeshk2846/Data_Scientist_Agent.git
   cd Data_Scientist_Agent
   ```

2. Set up virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e "backend[dev]"
   pip install -r TextToSQL/requirements-dev.txt
   ```

TextToSQL's CPU embeddings and spreadsheet intake dependencies are optional;
install `TextToSQL/requirements-embeddings.txt` or
`TextToSQL/requirements-uci-intake.txt` only when using those features.

The Olist SQLite warehouse is not included in this repository. Obtain or build
it through a source whose terms permit your intended use, then set
`DS_AGENT_DATABASE` to its local path before running the database-backed API,
CLI, or integration tests. See [deployment readiness](docs/DEPLOYMENT_READINESS.md)
for the missing-fixture and authentication limitations.

### Running the Test Suite (TDD)
Run backend tests from `backend/`. Tests that use Olist's fixed data and expected
aggregates require the separately obtained database described above; unit tests
using temporary SQLite databases do not.
```bash
cd backend
python -m pytest
```

### Running the API
Start the FastAPI server from `backend/` (no Ollama required for governed questions):
```bash
uvicorn app:app --app-dir src --reload
```

Start a run, stream its progress, then fetch the final envelope:
```bash
curl -X POST http://127.0.0.1:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"How many orders were there in August 2018?","session_id":"demo"}'

curl -N http://127.0.0.1:8000/api/runs/<run_id>/events
curl http://127.0.0.1:8000/api/runs/<run_id>
```

SSE events use monotonically increasing `seq` values and support reconnect with
`Last-Event-ID`. The stream ends after `answer` or `error`; `GET /api/runs/{run_id}`
returns the complete `AnswerEnvelope`.

---

## 6. Development Roadmap

- [x] **Stage 1: Foundation, Read-Only Gateway & Safety Boundary (Sprint 1)**
  - Pydantic v2 contracts matching `Interfaces.md`
  - Ingress Guard blocking prompt injection and DDL/DML tokens
  - Read-only SQLAlchemy gateway connected to `brazil_ecommerce.sqlite`
  - SQLGlot AST Validator with Dual-Mode Toggle (Enterprise vs. Benchmark)
  - Test suite passing (`backend/tests/test_*.py`)
- [x] **Stage 2: Interactive Console REPL, Trace Logger & Baseline A (Sprint 2)**
  - Rich console REPL with read-only SQL, `ask`, `tables`, `mode`, and `help`
  - Masked structured JSON traces for every run
- [ ] **Stage 3: Native 4-Stage NL2SQL Engine & Bounded Reflector (Sprint 3)**
  - [x] Schema catalog, answerability gate, and deterministic value perception
  - [x] Deterministic CTE generator with inferred joins and frozen allowlists
  - [x] Bounded self-repair with structured clarification
  - [ ] Hybrid keyword/dense retrieval and cross-encoder reranking
- [x] **Stage 4: Deterministic Metric Compiler Fast-Path, Resolver & Reconciler (Sprint 4)**
  - Governed metric registry and deterministic resolver for GMV, revenue, order count and AOV
  - Strict Jinja2 compiler with catalog join paths, allowlists and SQLGlot validation
  - Local Ollama `deepseek-r1:7b` client for complex metric mapping and flagged-result diagnosis
  - Post-execution grain, duplicate/fan-out, null, range and registry-total reconciliation
- [x] **Stage 5: End-to-End Orchestrator DAG & Analyst Harness (Sprint 5)**
  - Three-signal router with deterministic rules, catalog classifier and optional local-model tie-break
  - Orchestrator DAG with query, token and wall-time budgets; risk requests fail closed as `insufficient_evidence`
  - Pure-Python anomaly and driver analysts behind a typed `AnalystHarness`
  - CLI diagnostic flow with SQL/data, anomaly verdict and driver contribution tables
- [ ] **Stage 6: FastAPI Production Server, SSE Streaming & Evaluation Harness (Sprint 6)**
  - [x] Numbered evidence ledger for query rows and analyst outputs
  - [x] Deterministic fact checker for unapproved numbers and causal wording
  - [x] `POST /api/ask`, `GET /api/runs/{run_id}`, and SSE `GET /api/runs/{run_id}/events` with replay
  - [ ] Evaluation harness and frontend integration

---

## 7. Governing Specifications & Traceability
Every commit, test, and module in this repository maps directly to our formal specifications:
* [spec/requirements.md](spec/requirements.md) — Normative requirements (`SAFE-1`, `SQL-1`, `EVAL-1`).
* [spec/Interfaces.md](spec/Interfaces.md) — Data contracts and system boundary interfaces.
* [docs/DESIGN_DETAIL.md](docs/DESIGN_DETAIL.md) — Master architecture blueprint and sequence diagrams.
* [spec/build-plan.md](spec/build-plan.md) — Engineering delivery milestones.

---

## 8. License
This project is developed under the MIT License.
