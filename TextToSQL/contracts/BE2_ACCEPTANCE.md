# BE-2 acceptance matrix

This matrix is the workspace audit against `Data_Scientist_Agent/docs/Product.md`
§4.4 (pipeline, stores, trust layer, generator) and
`Data_Scientist_Agent/spec/requirements.md`. Reference documents are read-only.
Rows outside the BE-2 ownership boundary are listed as integration dependencies,
not silently treated as delivered. `PARTIAL` means some local behavior exists
but the acceptance criterion is not fully implemented or evidenced.

| Requirement | Acceptance summary | Implementation and coverage | Remaining work / blocker | Validation | Status |
|---|---|---|---|---|---|
| 4.4.1 Stage 0 / GRD-1 | Verify connection, dialect and read-only mode | `pipeline.py::_connect_info`; read-only SQLite connection and integration tests | SQLite only; external grants/filesystem permissions cannot be audited | `python -m pytest -v -p no:cacheprovider tests/test_query_knowledge_integration.py` | PARTIAL |
| 4.4.1 Stage 1 / GRD-1 | Introspect DDL, columns, constraints, counts and freshness fields | `inspector.py`; `test_inspector_and_profiler_legacy_shapes_remain_available` | SQLite only; timestamp conventions are heuristic | targeted integration suite | PARTIAL |
| 4.4.1 Stage 2 / GRD-1 | Profile columns with bounded samples and documented estimates | `profiler.py`; profiler and pipeline tests | Large-table exact distinct/range stats and full cost budget are not measured | `python -m pytest -v -p no:cacheprovider tests/test_privacy.py tests/test_pipeline_trust.py` | PARTIAL |
| 4.4.1 Stage 3 / SAFE-5 | Detect/review sensitive fields and exclude values from artifacts | `privacy.py`, pipeline masking; canary artifact tests | Detection is bounded and cannot prove all warehouse values safe | `python -m pytest -v -p no:cacheprovider tests/test_privacy.py tests/test_query_knowledge_integration.py` | PARTIAL |
| 4.4.1 Stage 4 / GRD-3 | Freshness, counts, duplicates, usage and stale-copy signals | `pipeline.py::_trust`; `test_freshness_duplicate_uncertainty_and_stale_copy_link` | No warehouse query logs; usage unknown; stale-copy heuristic | `python -m pytest -v -p no:cacheprovider tests/test_pipeline_trust.py` | PARTIAL |
| 4.4.1 Stage 5 / GRD-2 | Declared and inferred joins with evidence, cardinality and review | `pipeline.py::_joins`, `approve_review`, and local `OnboardingService` review queue/decision methods; join governance and service tests | Inferred comparison samples are capped; authenticated HTTP and review UI remain BE-1/FE-1 handoffs | `python -m pytest -v -p no:cacheprovider tests/test_join_governance.py tests/test_onboarding_service.py` | PARTIAL |
| 4.4.1 Stage 6 | Preserve descriptions; unreviewed drafts stay drafts | `pipeline.py::_descriptions`, `review_descriptions`, `__main__` review flags; `test_description_drafts_require_approval_before_publication` | CLI/API only; no graphical review UI or model draft generator | `python -m pytest -v -p no:cacheprovider tests/test_description_review.py` (2 passed) | PASS |
| 4.4.1 Stage 7 / GRD-4, GRD-8 | Keyword/dense/value indexes; avoid sensitive values | `pipeline.py` keyword + versioned local dense index stage; `ValueIndex`; retrieval/privacy tests | Dense vectors use non-learned feature hashing; cross-encoder absent; high-cardinality value index remains sample-based | targeted retrieval/privacy suite | PARTIAL |
| 4.4.1 Stage 8 / GRD-12 | Graph contains catalog, join, metric, term and stale-copy relations and supports bounded queries | `pipeline.py::_graph`; `catalog_api.py::KnowledgeGraph`; `test_graph_query_layer_exposes_nodes_neighbors_and_paths` | Local JSON graph only; no graph-store query service | integration, join-governance and pipeline-trust tests | PARTIAL |
| 4.4.1 Stage 9 | Self-test retrieval and sensitive artifact checks | `pipeline.py::_self_test`; demo | Checks are bounded; no proof for unobserved values or all table pairs | `python -m src.onboarding.demo` | PARTIAL |
| 4.4.1 Stage 10 / 5.6 | Report counts, warnings, stages and timings | `pipeline.py::build_catalog`; job/report artifacts | No FE progress stream or scheduled runner | demo and pipeline tests | PARTIAL |
| 4.4 pipeline idempotency/resume | Versioned, idempotent, resumable build with recoverable stage failure | `pipeline.py` writes `published.json` last with catalog/index hashes; `CatalogAPI` fails closed on any artifact/publication mismatch. `test_catalog_and_index_share_publication_version`, `test_process_crash_matrix_fails_closed_or_resumes`, `test_failed_stage_is_reported_and_resumes_without_catalog_corruption` | Non-query artifacts are not swapped by one filesystem transaction, but readers only serve the committed manifest generation; four process-crash windows are covered | `python -m pytest -v -p no:cacheprovider tests/test_pipeline_trust.py` (8 passed) | PASS |
| 4.4 incremental refresh / GRD-12 | Detect changed/removed tables and rebuild dependent artifacts | Table signatures and selective profile/index refresh; row-content hashes added when warehouse file changes; same-count regression test | Changed-source detection scans each table; no scheduled refresh service | `python -m pytest -v -p no:cacheprovider tests/test_query_knowledge_integration.py` | PARTIAL |
| 4.4 scale | Rebuild 50/200/500-table sources and report time/cost | `data_gen/generator.py`, `src/onboarding/scale_report.py`, `contracts/BE2_SCALE_REPORT.md` | Reproducible sweep passed (1.416 s / 2.471 s / 4.787 s onboarding; 248 / 998 / 2498 dense vectors) on Python 3.13.2, Windows 11, seed 7; timings are local single observations and no cloud cost/SLA was measured | `python -m pytest -v -p no:cacheprovider tests/test_scale_report.py` (1 passed); `python -m src.onboarding.scale_report --sizes 50 200 500` | PARTIAL |
| GRD-4 | Keyword+dense RRF and cross-encoder reranking | Persisted local hashed n-gram vectors; six-case fixture measures hybrid recall@1/MRR 1.00/1.00 versus keyword-only 0.50/0.50; injected adapter test covers reranker interface | No learned semantic encoder, model weights, cross-encoder or representative corpus; feature hashing is lexical | `python -m pytest -v -p no:cacheprovider tests/test_retrieval_eval.py` (3 passed, 2026-10-29) | PARTIAL |
| GRD-5, GRD-6, GRD-7, GRD-9, GRD-10 | Confidence refusal, approved join expansion, pruning, warnings and context bound | `retrieval.py`, `spike.py`; integration tests | Confidence not calibrated against labeled corpus; no tokenizer installed/configured | `python -m pytest -v -p no:cacheprovider tests/test_query_knowledge_integration.py` | PARTIAL |
| GRD-11 | Business synonyms and annotations are searchable | `_indexes`, `_graph`, `CatalogAPI.search`, `retrieval.py::_expand_synonyms`, `contracts/BE2_SYNONYMS.json` | Seed set is initial/local, not business-approved; six curated paraphrase cases on synthetic data | `python -m pytest -v -p no:cacheprovider tests/test_synonym_recall.py` (1 passed) | PARTIAL |
| 4.4.2 Metric Registry / MET-1, MET-6 | Versioned metric schema and named human approval | `stores.py::MetricRegistry`; governance tests | No seed set, service authorization or query resolver integration | `python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py` | PARTIAL |
| 4.4.2 Golden Store / OPS-8, DATA-8 | Result checks, human approval, development-only material, required non-empty held-out comparison set, held-out retrieval exclusion and pre-scorer leakage gate | `stores.py::GoldenStore`, `evaluation.py`; `test_golden_heldout_material_cannot_be_promoted_or_retrieved`, `test_final_evaluation_checks_leakage_before_calling_scorer` | Leakage checker is a local lexical heuristic and caller still supplies the comparison set | `python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py` (7 passed) | PARTIAL |
| 4.4.2 Trace Store / OPS-1 | Redacted per-step event persistence with timing/tokens/cost/retries fields | `stores.py::TraceStore`, `spike.py`; trace regression tests | Local JSON, some stages lack token/cost measurements, retrieval tokens are estimates | targeted trace/store suite | PARTIAL |
| 4.4.2 Cache storage | Version-bound cached values | `stores.py::CatalogCache`; trust-store tests | Not permission-scoped or distributed | `python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py` | PARTIAL |
| 4.4.2 Action Library | Store and match curated action metadata | `stores.py::ActionLibrary`; trust-store tests | Content/seed library owned by AN-1 is absent | `python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py` | PARTIAL |
| 4.4.3 EVID-2 | Claims have IDs, query/module links, grade and provenance | `ledger/evidence.py`; evidence tests; checker now requires a valid 0–4 grade on linked evidence | Current query ID is constant and app/module artifact linkage is absent | `python -m pytest -v -p no:cacheprovider tests/test_evidence_ledger.py` (15 passed, 2026-10-29) | PARTIAL |
| 4.4.3 EVID-3, EVID-5 | Ledger-only synthesis; deterministic fallback | `ledger/synthesizer.py`, `EvidenceLedger`; evidence tests | No deployed narrative workflow | `python -m pytest -v -p no:cacheprovider tests/test_evidence_ledger.py` | PARTIAL |
| 4.4.3 EVID-4 | Unsupported numbers/dates and causal claims rejected | `FactChecker.verify`; grade-gated evidence and exact numeric/date matching; adversarial number, date, and causal tests | Date forms outside the implemented ISO, US numeric and common English month styles need broader application evaluation | `python -m pytest -v -p no:cacheprovider tests/test_evidence_ledger.py` (15 passed, 2026-10-29) | PARTIAL |
| SAFE-7 | No repository secret leakage | `.gitignore`, `env.example` | No secret-scan hook/history scan; `.env` intentionally not read; no Git metadata | No credential-bearing scan run | PARTIAL |
| 4.4.4 / DATA-2, DATA-3 | Seeded configurable 50/200/500 synthetic warehouses with required defects | `data_gen/generator.py`; generator tests | Some edge cases are summary labels rather than independently scored scenarios | `python -m pytest -v -p no:cacheprovider tests/test_generator.py` | PARTIAL |
| 4.4.4 / DATA-4, DATA-5 | Planted-truth plugin, separate manifest and two snapshots | `generator.py`, `scoring.py`; generator tests | Filesystem/process isolation is not enforced | generator tests | PARTIAL |
| DATA-1, DATA-7 | Three data layers and provenance for each source | Spider 1.0 source, CC BY-SA 4.0 licence, citation/DOI, development split, and local snapshot hash are recorded; synthetic generation has per-snapshot provenance; UCI Online Retail II is a verified, not-ingested development candidate | Transactional file not downloaded pending customer-ID privacy review; Spider upstream package revision/date is unknown | `python -m pytest -v -p no:cacheprovider tests/test_generator.py` (10 passed) and reproducible Spider directory hash | PARTIAL / intake BLOCKED |
| DATA-6, DATA-9 | Development and held-out files separated; truth separate from public manifests; held-out reads restricted to scoring call path | `splits.py`, generator, `test_heldout_question_access_is_scoring_only_and_immutable`; pre-scorer gate test | Same-user workspace file access remains possible; separate OS identity/protected service storage unavailable | `python -m pytest -v -p no:cacheprovider tests/test_generator.py tests/test_trust_stores.py` | BLOCKED for enforced isolation |
| OPS-9 | Development-only feedback capture, evaluated before retraining | `FeedbackStore`; trust-store tests | No scheduled retraining or router/retriever update job | `python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py` | PARTIAL |
| Deployment / 4.4.4 | Reproducible local run and safe environment template | `env.example`, CLI, demo | Public app/hosting, authenticated API and secret-service decision absent | demo / CLI inspection | BLOCKED |

## Cross-component requirements outside BE-2 ownership

The source requirements also assign work to BE-1, AN-1 and FE-1. This matrix
does not mark those owners' work complete. In particular, RTE-1–7, MET-2–5,
SQL-1–17 and ABS-1–4 are BE-1 requirements; ANA-1–5, ANOM-1–9, DRV-1–10 and
REC-1–5 are AN-1 requirements; EVAL-1–8 are primarily AN-1; UI-1–6 are FE-1;
and DEL-1–6 are shared delivery requirements. This workspace has a local
SQLite `spike.answer` integration and shared ledger/store tests, but it has no
full application service, authentication layer, analyst modules, public UI,
deployment or committed evaluation harness/results. Cross-owner acceptance
therefore remains unverified or blocked. `SAFE-5`, `SAFE-7`, `GRD-10`, `EVID-2–5`
and `OPS-1` are shared/local slices and retain their PARTIAL limits documented
above.

## Current change evidence

- Same-row-count refresh defect: before the fix, the new regression test failed
  because `changed_tables` was empty. The first content-hash implementation then
  flagged an untouched table because `sqlite3.Row` object representations were
  hashed. Hashing tuple values fixed both defects.
- Recovery defect: stage exceptions previously left `job.json` in `running`
  state without a failure record. Stage failure now records a redacted error,
  duration and timestamp; a same-input rerun resumes successfully.
- Golden Store rejection audit: rejecting a candidate without a reason is now
  rejected; a valid reason is persisted with reviewer and timestamp. Regression
  coverage is in `test_golden_candidate_requires_each_check_and_person_decision`.
- Retrieval evaluation: the three-case deterministic fixture executes the
  current keyword retriever and computes recall@1 and MRR; both are 1.0 on this
  deliberately small fixture, with no claim about production or dense retrieval.
- Latest targeted commands after these changes:
  - `python -m pytest -v -p no:cacheprovider tests/test_query_knowledge_integration.py::test_refresh_detects_same_row_count_data_edits_without_watermark` — 1 passed.
  - `python -m pytest -v -p no:cacheprovider tests/test_pipeline_trust.py::test_failed_stage_is_reported_and_resumes_without_catalog_corruption` — 1 passed.
  - `python -m pytest -v -p no:cacheprovider tests/test_pipeline_trust.py tests/test_query_knowledge_integration.py tests/test_join_governance.py` — 16 passed.
- Current suite: `python -m pytest -v -p no:cacheprovider` — 55 collected,
  54 passed, 1 skipped (opt-in live LLM), 0 failed; exit code 0.
- Current targeted privacy/retrieval/trust/ledger/generator command passed 50
  tests. The onboarding demo exited 0 with a 50-table self-tested catalog and
  three trace events. Exact output is recorded in `BE2_PROGRESS.md`.

## Continuation verification (2026-10-29)

This run supersedes the historical suite count above: the complete suite
collected 59 tests, with 58 passed, 1 opt-in live-LLM test skipped, and 0
failures. The affected evidence/privacy/store/join/query integration suite
passed 42 tests. The ledger suite passed 15 tests after adding date comparison,
valid-grade enforcement for linked evidence, and case-insensitive verification
of the mandatory E5 note. The new date tests cover equivalent ISO and English
month formats and reject an unsupported date.

The onboarding demo exited 0 with 50 tables, a passing self-test, the demo query
returning 600, and 3 trace events. A fresh temporary generator-plus-onboarding
scale run passed self-tests at 50, 200, and 500 tables (6.337 s, 6.845 s, and
4.080 s elapsed, respectively; one run per size). Each remained `needs_review`,
as expected for generated datasets with pending reviewer decisions. These
timings are environment observations only. Privacy tests are included in the
42-test targeted run and the full suite.

BE-2 remains PARTIAL. Current executable local evidence does not make dense
retrieval complete: the configured demo remains keyword-only and has no real
embedding or cross-encoder model. The held-out scoring role is an in-process
caller convention, public transactional dataset provenance is unavailable,
and production service/authentication/deployment dependencies remain open.

## BE-2 continuation audit and current evidence (2026-10-29)

The original 59-test baseline passed 58 tests with 1 opt-in live-LLM test
skipped. Following the continuation changes, the required full command
`python -m pytest -v -p no:cacheprovider` collected 62 tests: 61 passed, 1
skipped, 0 failed.

| Gap audited | Current implementation and executable evidence | Status / remaining boundary |
|---|---|---|
| GRD-4 local dense backend | `src/knowledge/dense_index.py` signed word/character n-gram vectors persisted in `index_build.json`, with encoder/corpus/index versions, cosine scores and keyword RRF. Corrupt payload falls back and rebuild repairs it. `tests/test_retrieval_eval.py`: 3 passed. | Local lexical vector baseline tested. Learned semantic model, model weights, and cross-encoder unavailable; no production-scale retrieval corpus. |
| GRD-4 quality | Six deterministic exact/typo questions on a fixed 3-table catalog. Measured hybrid recall@1 1.00, MRR 1.00; keyword-only ablation recall@1 0.50, MRR 0.50. | Reproducible fixture result only; not representative production quality. |
| GRD-12 dense rebuild and incremental refresh | Repeat build produced same content-derived index version; unchanged vectors reused after invoice schema change; corrupt vectors were rejected and repaired. | Dense metadata/index rebuild is local; no model version lifecycle or distributed vector service. |
| SAFE-5 dense artifact privacy | Vectors are built only after masking/redaction. `test_pipeline_masks_canary_from_all_json_artifacts` now asserts masked columns have no dense vectors. | Bounded masking detection remains a limit; complete arbitrary-source privacy cannot be proven. |
| DATA-6 split handling | Development and held-out questions persist to separate files; unauthorized held-out retrieval fails; immutable split test passed. | Caller role gate remains application-level. |
| DATA-8 leakage gate / Golden promotion | Promotion/approval requires a non-empty held-out set, only development material can be approved, held-out rows are excluded from nearest lookup; final evaluation checks before scorer callback. `tests/test_trust_stores.py`: 7 passed. | Caller may still provide an incomplete set; lexical similarity is heuristic. |
| DATA-9 truth isolation | Truth manifests and held-out rows are separate from public/development artifacts; denial tests pass. | **Blocked:** same-user file access remains. No scoring account/service principal or protected storage/ACL is available in this environment. |
| DATA-1 transactional layer / DATA-7 provenance | Official [UCI Online Retail II record](https://archive.ics.uci.edu/dataset/502/online+retail+ii) confirms transaction data and CC BY 4.0 attribution terms; candidate and citation/DOI are recorded. Official [Spider 1.0 page](https://yale-lily.github.io/spider) confirms Spider 1.0 and CC BY-SA 4.0; local snapshot hash `808f8d66cb8ab5d066af3934047cc02bde555db28d4149310984f805af90a844` is recorded with citation/DOI. | UCI candidate is development-only and `candidate_not_ingested`; CustomerID privacy assessment, download, hash, and transformed reproducible intake remain. Spider upstream revision/date is unknown; workspace snapshot is reproducible by recorded hash. |
| Production onboarding/review/deployment | Local CLI/build stages and newly added persistent Python `OnboardingService` facade cover start/status/report/refresh/review interfaces, backed by named-reviewer workflow, JSON audit and stage recovery. | **Production remains unimplemented:** service calls are synchronous and unauthenticated; no API/service DB, scheduled runner, reviewer identity provider, hosting target, or deployment credentials. BE-1 API/auth, FE-1 screens, AN-1 truth/scoring, and provisioned infrastructure are required handoffs. |

Current targeted verification after the above changes:

```text
python -m pytest -v -p no:cacheprovider tests/test_retrieval_eval.py
3 passed.
python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py tests/test_generator.py::test_heldout_question_access_is_scoring_only_and_immutable tests/test_privacy.py::test_pipeline_masks_canary_from_all_json_artifacts tests/test_retrieval_eval.py
12 passed.
python -m pytest -v -p no:cacheprovider
62 collected; 61 passed, 1 skipped, 0 failed.
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; query returned 600; hybrid mode;
3 trace events; temporary artifacts removed.
```

Fresh temporary scale runs (seed 7, generator plus onboarding) passed self-tests
at 50, 200 and 500 tables in 1.315 s, 2.381 s and 4.589 s. The corresponding
local dense indexes contained 248, 998 and 2,498 vectors. These single-run
figures are not service-level performance evidence.

**Overall status: PARTIALLY COMPLETE.** Local dense-vector retrieval, split
separation, fail-closed Golden promotion and provenance candidate tracking now
have implementation and tests. Learned semantic retrieval, OS-enforced
held-out isolation, actual transactional data intake pending privacy review,
upstream Spider revision identification, and production service/deployment remain blocked or
unimplemented as described above.

## Product.md service-interface continuation (2026-10-29)

| Product requirement | Implementation and verification | Remaining boundary | Status |
|---|---|---|---|
| 5.1/5.7 onboarding service functions | `src/onboarding/service.py::OnboardingService` implements start, persisted status/report lookup, refresh, join/sensitive review queues and named decisions; decisions rebuild to publish. `tests/test_onboarding_service.py` covers persistence, review, refresh, errors and unknown job IDs. | Synchronous local runner; BE-1 must wire authenticated HTTP routes and authenticated reviewer identity. FE-1 screens remain external. | PARTIAL |
| 5.1 Golden and Registry review service functions | Facade lists proposed Golden/metric records and delegates decisions to existing gated stores. Service integration test covers rejection audit and metric approval. | Golden approval requires evaluation question set from caller; route authorization and identity remain BE-1. | PARTIAL |
| Persistence and restart | Job mapping, job artifacts, reports and review records reopen from local JSON after constructing a new service instance. | No concurrent-process locking or production transactional database. | PARTIAL |

Actual verification after this continuation:

```text
python -m pytest -v -p no:cacheprovider tests/test_onboarding_service.py tests/test_pipeline_trust.py tests/test_join_governance.py tests/test_trust_stores.py
16 passed.
python -m pytest -v -p no:cacheprovider
66 collected; 65 passed; 1 opt-in live-LLM test skipped; 0 failed.
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; hybrid query returned 600; 3 trace events.
```

Fresh temporary scale sweep using seed 7 passed onboarding self-tests at 50,
200, and 500 tables (1.271 s, 2.332 s, and 4.565 s); dense vector counts were
248, 998, and 2,498. This supersedes the prior one-run timings above for this
date; timings are environment-specific, not SLA evidence.

The BE-2 workspace itself has no `.git` directory, so teammate commits or
pushes could not be enumerated from local Git metadata. Public GitHub branch
and commit endpoints were not accessible in this run; Product ownership was
audited from the included read-only `Data_Scientist_Agent/docs/Product.md`
snapshot. This evidence does not establish the current state of remote pushes.

**Status remains PARTIALLY COMPLETE.** No end-to-end production API/auth,
scheduled refresh service, process-isolated held-out storage, downloaded
transactional dataset, learned semantic model or deployment environment was
available to implement and verify here.

## Operational hardening continuation (2026-10-29)

| Requirement | Implemented and verified | Remaining boundary | Status |
|---|---|---|---|
| Durable asynchronous onboarding and refresh jobs | SQLite/WAL job registry, bounded worker pool, persisted job state, status/report, retry, stale-lease recovery; service integration tests cover failures and recovery. | Single-node local adapter; no hosted worker process supervision or distributed deployment evidence. | PARTIAL |
| Scheduled refresh | Persisted per-job intervals, due-job queueing, stoppable polling loop, `python -m src.onboarding.worker`; schedule persistence and due-time tests pass. | A supervisor/host must run the worker continuously in production. | PARTIAL |
| Concurrent local store updates | Process-safe lock files plus atomic replace around Metric, Golden, Trace, Cache, Action and Feedback JSON read-modify-write. Tests retained all revisions across 20 threads and 12 proposals from four processes. | Local files are not a managed multi-node database; ACL/backup/retention policies remain unconfigured. | PARTIAL |
| Failure recovery | Explicit expired worker lease marking/retry, 10-second active-job heartbeat, and underlying build-stage retry. Simulated disk failure and interrupted-job recovery test passes. | No process-kill or host-failure chaos matrix. | PARTIAL |

Latest verification supersedes earlier totals:

```text
python -m pytest -v -p no:cacheprovider tests/test_onboarding_service.py
6 passed.
python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py tests/test_onboarding_service.py tests/test_query_knowledge_integration.py
24 passed.
python -m pytest -v -p no:cacheprovider
70 collected; 69 passed; 1 opt-in live-LLM skipped; 0 failed.
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; hybrid query returned 600; 3 trace events.
python -m src.onboarding.worker --help
exit 0.
```

Fresh seed-7 temporary scale checks passed self-tests: 50 tables (248 vectors,
1.321 s), 200 (998 vectors, 2.440 s), 500 (2,498 vectors, 4.710 s). Timings
are single-run local observations only.

**Overall remains PARTIALLY COMPLETE.** Learned semantic retrieval is blocked
by absent model packages/weights or a configured service. OS-enforced held-out
separation requires a separate scoring identity and protected storage. The
transactional source remains un-ingested pending privacy approval. Production
deployment is blocked by the absent authenticated app, hosting target and
deployment credentials. No dependency installation, secret access, or public
deployment was attempted.

The cross-process regression command
`python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py::test_cross_process_metric_proposals_keep_every_revision`
passed (1 test). The latest full suite now collects 71 tests: 70 passed, 1
opt-in live-LLM test skipped, 0 failed. This is a local file-lock verification,
not evidence of multi-host persistence.

## Current continuation evidence (2026-10-29)

This section supersedes historical suite totals and earlier claims that no
learned model integration or transactional intake code exists.

| Requirement | Current implementation and verification | Remaining limitation | Status |
|---|---|---|---|
| GRD-4 optional learned embeddings/reranking | Pinned Apache-2.0 model adapters, local-only loading, explicit model asset downloader, model/version metadata in dense index, version mismatch rejection, CLI and service wiring. `tests/test_retrieval_eval.py`: adapter/index regression tests passed (5 tests). | Runtime, weights and cache are absent; no run with actual model artifacts and no learned-model quality measurements. The 1.00 recall@1/MRR fixture remains hashed lexical baseline only. | PARTIAL |
| DATA-1 transactional intake implementation | Opt-in XLSX-to-SQLite importer drops CustomerID, deterministically remaps invoice IDs, preserves duplicate rows, refuses overwrite, hashes source/output, and writes development provenance. Synthetic-row tests verify privacy transformation and preservation (3 passed). | Real UCI source not downloaded or ingested. Non-empty approval reference is an operator assertion, not validated approval. Optional `openpyxl==3.1.5` absent. | PARTIAL / intake not performed |
| DATA-7 provenance | Intake record can store source URL, dataset/version, CC BY 4.0, permitted-use summary, development split, source/artifact hashes and transformation. Provenance write runs only after local import. | No actual source hash or artifact evidence until reviewed source is provisioned and imported. | PARTIAL |
| DATA-6/9 held-out access boundary | Existing split separation, role checks and negative tests remain. | Role check is application-level only; workspace has one current OS identity and no protected scoring storage/account. No enforceable authorization boundary established. | BLOCKED for OS enforcement |
| OPS production onboarding/review/deployment | Durable local async jobs/schedule state, worker, process-safe JSON mutations and service review interfaces remain tested. | Authenticated production API, reviewer identity provider, hosted worker/deployment, secret manager and target environment are not available; BE-1/operations handoffs required. | PARTIAL / external blockers |

Environment inspection (no secrets read) found `sentence_transformers`, `torch`,
`huggingface_hub`, and `openpyxl` unavailable and no configured model cache.
No dependencies were installed and model downloads were not attempted. This is
why the learned model path is integrated but not reported as production-tested.

Executed validation:

```text
python -m pytest -v -p no:cacheprovider tests/test_transactional_intake.py tests/test_retrieval_eval.py
8 passed.
python -m pytest -v -p no:cacheprovider
76 collected; 75 passed; 1 opt-in live-LLM test skipped; 0 failed.
python -m src.knowledge.model_assets --help
exit 0.
python -m src.onboarding build --help
exit 0.
python -m src.onboarding.demo
exit 0; 50-table self-test passed; SQL returned 600; 3 trace events.
seed-7 temporary scale sweep
50/200/500 tables passed; 248/998/2,498 vectors; 1.314/2.458/4.790 seconds.
```

Overall status remains **PARTIALLY COMPLETE**. Local interfaces and regression
evidence improved; actual learned inference, real third-layer data intake,
OS-enforced held-out protection, and production deployment remain unverified
or externally blocked.

## Publication-consistency continuation (2026-10-29)

The idempotent/resumable-build criterion is now PASS. `pipeline.py` writes
`published.json` last with SHA-256 hashes of the build artifacts; `CatalogAPI`
validates the catalog and index against the manifest and fails closed on a
partial publication. `test_process_crash_between_index_and_catalog_is_fail_closed_and_resumable`
kills a refresh subprocess in the index/catalog window, verifies readers reject
the mixed generation, and verifies rerun recovery. The full suite passed: 77
passed, 1 opt-in live-LLM test skipped, 0 failed. Remaining limitation: other
non-query artifacts are not swapped by one filesystem transaction, though
readers only serve the committed manifest generation.

### Learned retrieval integration update (2026-10-29)

The runtime path now carries an injected encoder through both catalog build and
query in `spike.answer()`. `--learned-retrieval` on the spike CLI loads the
pinned local embedding and reranking models explicitly. Runtime reranker errors
fall back to deterministic RRF ordering and mark the response's retrieval mode
as degraded. A reproducible 12-case evaluation runner reports Recall@1 and MRR.
Tests verify these integration and failure-recovery paths with fixture models.

```text
python -m pytest -v -p no:cacheprovider tests/test_retrieval_eval.py::test_reproducible_learned_model_evaluation_harness_reports_metrics tests/test_query_knowledge_integration.py::test_query_entrypoint_builds_with_learned_encoder_and_recovers_reranker_failure
2 passed.
python -m src.knowledge.evaluate_retrieval --help
exit 0.
python -m pytest -v -p no:cacheprovider
88 collected; 87 passed; 1 opt-in live-LLM skipped; 0 failed.
```

**GRD-4 remains PARTIAL:** actual model runtime and both model snapshots are
absent from the environment. The evaluation harness has not produced real
model scores. The last outbound HTTPS attempt was denied; the model download
was not retried. Use a permitted network environment or provision the pinned
model files and dependencies, then run
`python -m src.knowledge.evaluate_retrieval` and record its actual metrics.

### Additional BE-2-only acceptance evidence (2026-10-29)

| BE-2 requirement | New implementation/evidence | Status and remaining condition |
|---|---|---|
| Metric Registry seed content | Three complete synthetic-demo proposals with stable IDs, required schema, explicit caveats, and seed-7 reconciliation values. `data/metric_registry.json` contains three `proposed` rows. Re-seeding is idempotent; test independently checks reconciliation values. | Local seed content implemented. Human review is still required; these demo metrics must not be treated as business-approved or applied to unrelated warehouses. |
| Synthetic generator defects and snapshots | Read-only auditor checks 17 planted properties, manifest/database hash, and private truth SQL reconciliation. Generator version 5 binds truth manifest to warehouse SHA-256; scoring loader supports old v4 files. Positive audit: 17/17 for 50/200/500 seed-7 warehouses and both members of a 50-table snapshot pair. Negative mutation test detects removed mess and hash mismatch. | Defect scoring now independently tested for these generated properties. Filesystem/OS secrecy of truth remains blocked on a separate scoring identity and protected ACL/storage. |
| Fact Checker date coverage | Added and tested ISO hyphen/slash/dot, compact YYYYMMDD, day-first/month-first numeric, month-name, ordinal, and abbreviated-month formats; unsupported date is rejected. | Broader natural-language and locale-specific dates may still require application evaluation. |
| Evidence query linkage | `spike.answer()` writes its unique run UUID as ledger `query_id`; BE-2 `artifact` linkage remains available for module artifacts. Integration test asserts emitted run ID. | Query linkage implemented locally. Production orchestration must preserve the ID (BE-1), and analyst modules must provide artifacts (AN-1). |
| Dense retrieval with actual weights | Encoder now passes through catalog build and query; optional CLI loads pinned local models; reranker failures retain RRF ranking with degraded mode; 12-case evaluator is reproducible. | Still PARTIAL: runtime and weights are absent and no real model metrics were measured. |
| UCI data provenance | Privacy-filtered local intake implementation remains tested on synthetic rows. | No source workbook or organizational privacy approval exists in the workspace; no real data intake/hash has occurred. |
| Deployment and held-out enforcement | Local worker, durable jobs, schedule, and caller-level split controls are implemented/tested. | No deployment target/secrets environment or separate scoring OS identity/protected storage was provisioned. |

Latest full validation:

```text
python -m pytest -v -p no:cacheprovider tests/test_metric_seeds.py tests/test_generator_quality.py tests/test_generator.py tests/test_evidence_ledger.py tests/test_query_knowledge_integration.py
48 passed.
python -m pytest -v -p no:cacheprovider
99 collected; 98 passed; 1 opt-in live-LLM skipped; 0 failed.
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; result 600; 3 trace events.
scale report, seed 7
50/200/500 tables; 248/998/2,498 vectors; self-tests passed; onboarding 1.376/2.539/4.822 seconds.
generator quality audit
17/17 passed for 50/200/500 development snapshots and both 50-table pair snapshots.
```

The assigned BE-2 work remains **PARTIALLY COMPLETE** because actual learned
model evaluation, approved/ingested transactional data, OS-enforced held-out
isolation, and deployment on a provisioned target have not been verified.

## Existing implementation review and latest local evidence (2026-10-29)

The pass reviewed Product §4.4 and the corresponding GRD/MET/DATA requirements,
plus the current workspace's retrieval, metric store/service, transactional
intake/provenance, split/scoring, generator, trace/cache/feedback, LLM gateway,
CLI, demos, tests and fixtures. The nested `Data_Scientist_Agent` directory was
not modified.

| Area | Change/evidence | Updated status |
|---|---|---|
| GRD-4/5 retrieval | Model IDs can be overridden only with paired immutable 40-character revisions. Offline cache misses are explicit. Runtime embedding errors restart with deterministic hashed or keyword retrieval; reranker and embedding failures appear in mode/warnings, including clarification responses. Modes distinguish learned, hashed, reranked and fallback paths. Adapter/fixture tests exercise pin errors and deterministic fallbacks. | **PARTIAL** — no `sentence-transformers`, PyTorch, model cache or real model execution exists in this environment. The evaluation harness uses a 12-case synthetic schema fixture. No genuine model metrics are claimed. |
| MET-1/MET-6 metric review | Registry proposal fields are validated; review is deny-by-default unless a host authorization policy returns literal `True`; approval/rejection, reviewer, timestamp, redacted note, rejection reason and revision status are audited. Invalid and duplicate transitions fail. Service receives the authorizer as a dependency. | **Implemented/tested locally; PARTIAL as acceptance** — no authenticated identity provider or business reviewer was provisioned. `data/metric_registry.json` still contains three `proposed` demo metrics. |
| DATA-1/DATA-7 transactional intake | UCI workbook parsing streams rows; duplicate/missing headers and invalid numeric rows are rejected. Intake validates exact source/license/use metadata, schema, hashes, approval-record reference/status/scope/reviewer/timestamp, and provenance publication. Synthetic tests cover missing workbook, missing/mismatched approval, invalid provenance, malformed rows, and overwrite safety. | **BLOCKED for real intake** — no workbook or actual organization-provided approval record exists. The record checker validates structure; it cannot authenticate the issuing organization. `openpyxl` is unavailable and was not installed. |
| DATA-6/DATA-8/DATA-9 held-out boundary | Removed `role="scoring"`; held-out reads and truth loading require an injected allowlist policy and explicit principal. Final scorer callback runs in held-out scope; shared metric, Golden, trace, cache, action, feedback, split, generator and provenance writes are denied. Negative tests verify unauthorized reads, pre-scorer leakage checks, and blocked development writes. | **PARTIAL / BLOCKED for strong isolation** — Python callers can still read/write files directly or construct their own policy. A separate scoring identity, protected storage and independent ACL verification are required. |
| SAFE-7/configuration and deployment readiness | LLM URLs, transport security, placeholder keys, retry bounds and timeouts are validated without printing secrets. `python -m src.onboarding health --root .` reports local runtime, optional model/runtime/weight state, LLM configuration, and scoring principal count without a network request. Startup and external deployment checklist added in `BE2_DEPLOYMENT.md`. | **PARTIAL locally; BLOCKED for deployment** — no authenticated HTTP app, target, secret manager, identity service, public endpoint, or deployment credentials are available. Health output is not a service/ACL check. |
| OPS trace privacy | Canonical UUID run IDs are preserved as correlation metadata even when digit-based redaction patterns overlap; event text remains scrubbed. A deterministic overlap regression test passes. | **Implemented/tested locally** — no distributed trace store or access-controlled production persistence. |
| Synthetic DATA-2/3/5/7 provenance | Generator's already-computed database SHA-256 and version are recorded in its provenance row, required after stronger provenance validation exposed the missing fields. The 50/200/500 scale sweep still passes. | **Implemented/tested locally** — timings are one local measurement per size; strong truth secrecy remains blocked as above. |

### Final validation record

```text
Baseline: python -m pytest -v -p no:cacheprovider
99 collected; 98 passed; 1 opt-in live-LLM test skipped; 0 failed.

Final: python -m pytest -v -p no:cacheprovider
122 collected; 121 passed; 1 opt-in live-LLM test skipped; 0 failed (32.48 s).

Focused privacy/governance/leakage/intake/generator command:
python -m pytest -v -p no:cacheprovider tests/test_privacy.py tests/test_transactional_intake.py tests/test_trust_stores.py tests/test_generator.py tests/test_generator_quality.py tests/test_metric_seeds.py
40 passed; 0 failed.

python -m src.onboarding health --root .
exit 0; core local runtime ready; exact pins valid; model runtime/weights absent; LLM and scoring principal unset. No external service or ACL verified.

python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; query result 600; 3 trace events; hybrid_hashed mode; temp artifacts removed.

python -m src.onboarding.scale_report --sizes 50 200 500
exit 0; seed 7; all self-tests passed; 248/998/2,498 hashed vectors; 1.340/2.432/4.682 s onboarding. Refreshed report: `BE2_SCALE_REPORT.md`.

python -m src.onboarding review --help
exit 0; named reviewer required.

python -m src.knowledge.model_assets --help
exit 0; provisioning interface available; no model download attempted.
```

During the implementation loop, the first 49-test focused batch had 9 failures
and 40 passes; pin mismatch in the fallback fixture, missing generator hashes,
and changed metric rejection semantics explained them. The corrected 13-test
retest passed. A later 59-test focused batch had 4 failures and 55 passes due
old retrieval-mode assertions, a missing test fixture parameter, unvalidated
timeouts for injected clients, and missing degraded warnings on clarification.
Those were corrected; the affected combined suite passed 65 tests. A 120-test
full-suite attempt then had 118 passes, 1 skip and 1 remaining failure because
an onboarding service test still expected a reviewer string alone to
authorize. The test now injects a host authorization policy, and the focused
service test passed before the final full-suite run. No failure was silently
skipped or weakened.

One demo invocation during parallel checks exited with a trace-event count
error. Isolated reruns passed with 3 events. A UUID/PII-overlap case was
reproduced independently and fixed with a direct regression test. The initial
parallel-only demo failure did not recur in the final isolated demo. The
live-LLM skip is explicitly opt-in, not treated as a successful live-service
test.

### Reproducible follow-up when external inputs are provisioned

- **Pinned models:** in an approved network/build environment install
  `requirements-embeddings.txt`, set `TEXTTOSQL_MODEL_CACHE` and paired optional
  ID/revision variables, run `python -m src.knowledge.model_assets`, then
  `python -m src.knowledge.evaluate_retrieval`. Preserve the evaluator's actual
  JSON, pin identities and runtime versions. It is still a 12-case fixture, not
  production retrieval quality evidence.
- **Metric seeds:** an authenticated host must construct `OnboardingService`
  with a policy backed by its identity provider, derive reviewer IDs from the
  authenticated principal, and call `decide_registry` with actual human
  decisions. Re-read each revision's `decision_history`; do not use a caller
  supplied reviewer string as proof of identity.
- **Transactional data:** provide the actual reviewed UCI workbook, actual
  approval JSON record, and approved `openpyxl` runtime. Verify source URL,
  CC BY 4.0 use/attribution, approved status/scope/reviewer/timestamp, then run
  `python -m data_gen.transactional_intake` with the record reference/path and
  a new output path. Independently verify resulting provenance hashes and the
  dropped `CustomerID`/replaced invoice identifiers.
- **Held-out isolation:** provision the scoring OS account and storage outside
  developer ACLs; set principal policy through the trusted host; verify access
  as both developer and scorer; inspect ACLs independently; rerun leakage tests
  before allowing final scoring. Application tests alone cannot satisfy DATA-9.
- **Deployment:** select and provision the actual target and secret manager,
  configure settings outside source control, run `python -m src.onboarding health`
  and the smoke build under the deployed identity, then verify API auth,
  service health, backups, restore, ACL separation and secret non-disclosure.

Requirements that depend on these resources remain **PARTIAL** or **BLOCKED**.
No actual approvals, source workbook, model output, protected storage, secrets,
deployment, or Cadra submission were created in this pass.
