# BE-2 implementation and verification record

This record describes the current TextToSQL workspace, not the nested
`Data_Scientist_Agent` reference copy. Generated test/demo data uses temporary
directories. No Cadra trace has been submitted.

## Run locally

With the existing Python environment and dependencies, run:

```powershell
python -m src.onboarding build --warehouse <read-only-sqlite-path> --output <catalog-output>
python -m src.onboarding.demo
python -m pytest -v -p no:cacheprovider
```

The generator CLI supports `--tables 50`, `200`, or `500`. Do not point the
generator at an existing output path: it refuses to overwrite existing files.
Onboarding reads the warehouse read-only and writes its artifacts to the
separate output directory. A build with pending join or masking review ends in
`needs_review`; record named reviewer decisions using the review workflow, then
rerun the build to publish them.

## Requirement traceability

The requirement-level audit against Product §4.4 and the BE-2-owned/shared
requirements is maintained in [BE2_ACCEPTANCE.md](BE2_ACCEPTANCE.md). This is a
local acceptance matrix, not a claim that external services or other owners'
requirements are complete.

Status is scoped to the BE-2 responsibility and this workspace's tested
implementation. `PARTIAL` includes known integration, scale, production-model,
or isolation limits. `BLOCKED` means the current workspace lacks a needed
external service, dataset, or access boundary. Tests listed below were executed
with the final command above unless otherwise stated.

| Requirement | Implementation and evidence | Status | Remaining work |
|---|---|---|---|
| 4.4.1 Stage 0 connect | `src/onboarding/pipeline.py::_connect_info` opens SQLite read-only and checks `query_only`; `test_query_entrypoint_uses_retrieved_catalog_and_approved_join`, `test_inspector_and_profiler_legacy_shapes_remain_available`. | PARTIAL | Only SQLite is supported. External filesystem/credential write permissions are warned about but not audited. |
| Stage 1 introspect | `src/onboarding/inspector.py::inspect_warehouse`; emitted `introspect.json`; exercised by demo and `test_inspector_and_profiler_legacy_shapes_remain_available`. | PARTIAL | SQLite-specific; no connector coverage for declared source update watermarks across dialects. |
| Stage 2 profile | `src/onboarding/profiler.py::profile_database` profiles columns and deterministically samples tables over its row budget; `test_standalone_profiler_masks_values_and_partial_canaries`, `test_refresh_profiles_and_reindexes_only_changed_table`. | PARTIAL | Exact aggregate stats for large tables are sampled estimates; broader cost-budget and sampling validation absent. |
| Stage 3 mask | `src/onboarding/privacy.py`; `pipeline.py::_mask`, sensitive review, artifact sanitation; `test_pipeline_masks_canary_from_all_json_artifacts`, `test_cli_report_output_contains_no_canary`, `test_query_entrypoint_uses_retrieved_catalog_and_approved_join`, `test_trace_store_redacts_before_persistence`. | PARTIAL | Pattern/sample detection cannot prove all values in arbitrarily large tables are non-sensitive. No exhaustive artifact/secret scanner run. |
| Stage 4 trust_features | `pipeline.py::_trust`; freshness, count, PK duplicate groups, unknown duplicate signal without PK, stale-copy feature and graph edge; `test_freshness_duplicate_uncertainty_and_stale_copy_link`. | PARTIAL | Query usage is unknown without logs; freshness unknown without recognized update columns; stale-copy matching is heuristic. |
| Stage 5 join_discovery | `pipeline.py::_joins`, `approve_review`; declared FK approval, inferred proposed/verified state with type/name/value, uniqueness and containment evidence, cardinality and audit/invalidation; `OnboardingService` exposes local review queue/decision methods; governance and service tests pass. | PARTIAL | Empirical value/containment checks are capped samples. Authenticated route and review UI remain BE-1/FE-1 work. |
| Stage 6 descriptions | `pipeline.py::_descriptions` preserves supplied table/column text as `draft`; `review_descriptions` requires a named reviewer and stores approved text plus decision history; only approved text enters indexes or retrieval context; CLI supports `--approve-description TARGET=TEXT` and `--reject-description TARGET`; `test_description_drafts_require_approval_before_publication`. | PASS | CLI/API workflow only, no graphical review screen; model drafting remains optional and unimplemented. |
| Stage 7 index_build | Keyword documents, local hashed n-gram dense vectors, and Value Index; masked document filtering; versioned dense corpus/index metadata; deterministic retrieval evaluation. | PARTIAL | Local vectors are lexical feature hashing, not learned semantic embeddings; no real cross-encoder, and the evaluation corpus remains small. |
| Stage 8 knowledge_graph | `pipeline.py::_graph` creates table/column, join, metric, synonym and stale-copy relationships; generated in the E2E demo. | PARTIAL | No service integration or graph-store query layer beyond catalog artifact/API. |
| Stage 9 self_test | `pipeline.py::_self_test` checks table docs, sensitive artifacts and join paths; demo returned `passed: true`. | PARTIAL | Checks only bounded sensitive candidates and up to 20 discovered adjacent pairs; cannot prove unobserved warehouse values absent. |
| Stage 10 report/progress | `pipeline.py::build_catalog` writes report/job stage artifacts and build timings/counts; demo enumerated all stage artifacts. | PARTIAL | No FE onboarding progress display or scheduled job runner. |
| Idempotent, resumable, versioned build | Stage artifacts/job record and catalog version in `pipeline.py`; CLI; demo builds from scratch. `published.json` is written last as the commit manifest; `CatalogAPI` verifies catalog/index hashes against it and fails closed on a partial publication. | PASS | Publication is atomic at the reader boundary; non-query artifacts are not swapped by one filesystem transaction, but they are covered by the manifest. A four-point subprocess crash matrix covers profile, index, catalog and manifest publication windows. |
| Incremental refresh | Schema/count/watermark plus streaming table-content signatures when the SQLite file changes; only changed tables are reprofiled/reindexed; `test_refresh_profiles_and_reindexes_only_changed_table`, `test_refresh_detects_same_row_count_data_edits_without_watermark`. | PARTIAL | Content signatures require scanning table contents after source-file changes; no scheduled refresh service. |
| Failed-stage recovery | `pipeline.py::stage` records failed state, timestamp, duration and redacted error; same-input reruns retry incomplete stages; `test_failed_stage_is_reported_and_resumes_without_catalog_corruption`; `test_process_crash_matrix_fails_closed_or_resumes` interrupts profile, index, catalog and manifest writes. | PASS | Process interruption is tested for the publication windows; other stage artifacts are covered by rerun/retry rather than one filesystem transaction. |
| Human review gate | `approve_review` requires named reviewer; inferred joins must be verified; join evidence hash invalidates stale approvals; `test_join_governance.py`. | PARTIAL | No user-facing review screen; declared FK edges are system-approved by contract convention. |
| 5.6 onboarding job progress | `job.json` records stage state/count/timing in `pipeline.py`; the demo confirms stage artifacts exist. | PARTIAL | The job record is local and is not streamed to FE-1. |
| Scale 50/200/500 | `data_gen/generator.py`; `tests/test_generator.py` asserts exact table counts. Reproducible sweep: `python -m src.onboarding.scale_report --sizes 50 200 500`; checked-in `contracts/BE2_SCALE_REPORT.md` records 1.416 s / 2.471 s / 4.787 s onboarding and 248 / 998 / 2498 dense vectors on Python 3.13.2, Windows 11, seed 7. | PARTIAL | Timings are single local observations, not an SLA; no cloud spend or provider cost was measured. |
| 4.4 Done-when acceptance | `src/onboarding.demo` performs the fresh 50-table build/query; `test_refresh_profiles_and_reindexes_only_changed_table` checks selective refresh; ledger suite tests unsupported numbers and causal overclaims. | PARTIAL | No full clean-checkout rebuild matrix, real planted truth end-to-end score, operational refresh scheduler or independently isolated final evaluation. |
| Metadata Catalog/Join Graph/search/Value Index API (5.7) | `src/knowledge/catalog_api.py`; `CatalogAPI` consumed by `SchemaRetriever`; `KnowledgeGraph` exposes node/type lookup, neighbors with edge filtering and bounded BFS paths over catalog, join, metric, term and stale-copy edges; `test_graph_query_layer_exposes_nodes_neighbors_and_paths`, `test_query_entrypoint_uses_retrieved_catalog_and_approved_join`, `test_fuzzy_value_index_returns_confidence_and_sensitive_values_are_excluded`. | PARTIAL | Python/local JSON interface only; no HTTP API/vector service. |
| GRD-10 retrieval refusal (shared BE-1/BE-2) | `SchemaRetriever.retrieve` clarifies on no match, unmatched quoted values and over-budget context; integration tests cover those cases. GRD-4 keyword recall@1/MRR fixture also runs in `test_keyword_retrieval_fixture_reports_recall_and_mrr`. | PARTIAL | The curated fixture is small; confidence is not calibrated to the specified starting 0.65 threshold on a production retrieval corpus. |
| GRD-11 synonyms/business annotations | `_indexes` persists business-term synonyms; `SchemaRetriever._expand_synonyms` maps a matched alias to its canonical term before keyword ranking; `_graph` records synonym edges; `contracts/BE2_SYNONYMS.json` seeds 7 terms; `test_synonym_seed_improves_end_to_end_paraphrase_recall` scores 6/6 seeded paraphrase cases versus a lower no-term baseline. | PARTIAL | Seed set is an initial local set, not business-approved; evaluation has six curated cases on the synthetic warehouse. |
| GRD-12 rebuildability | CLI rebuilds catalog/index/graph from warehouse; dense vectors persist in `index_build.json` and rebuild from searchable docs; `src/onboarding.demo` rebuilds in a fresh temporary directory. | PARTIAL | Metric/Golden/Trace/Action stores are local stores but do not all have dedicated rebuild/import jobs; no dense learned model to rebuild. |
| Metric Registry, MET-1 | `src/knowledge/stores.py::MetricRegistry`; required schema and versioned proposed revisions; `test_metric_changes_require_named_approval_and_keep_revision_history`. | PARTIAL | No seed metric set supplied, UI or application query-path resolver integration. |
| Metric review, MET-6 | `MetricRegistry.decide` requires named reviewer and stores decision history; `test_metric_changes_require_named_approval_and_keep_revision_history`. | PARTIAL | Audit is local JSON without identity service/authorization. |
| Golden Store, OPS-8 | `GoldenStore.propose/decide/promote` gates development-only records on checks, named reviewer, and non-empty held-out question sets; held-out rows cannot be approved or retrieved; final evaluation checks leakage before scorer invocation. Evidence: `test_golden_promotion_requires_checks_human_and_no_heldout_leakage`, `test_golden_candidate_requires_each_check_and_person_decision`, `test_golden_heldout_material_cannot_be_promoted_or_retrieved`, `test_final_evaluation_checks_leakage_before_calling_scorer`. | PARTIAL | No authenticated production review API; callers can still supply an incomplete held-out set; leakage comparison is a local lexical heuristic. |
| Trace Store/cache/Action Library | `src/knowledge/stores.py::{TraceStore,CatalogCache,ActionLibrary}`; `test_trace_store_and_action_library_expose_expected_read_interfaces`. | PARTIAL | No distributed persistence, permission-scoped cache or complete per-step trace fields in the spike. |
| OPS-1 trace schema | `src/spike.py::answer` writes the retrieval event to `TraceStore` with run/step, redacted question input, selected tables/columns, confidence/mode/clarification status, measured `duration_ms`, `tokens.schema_estimated` from `RetrievedContext.estimated_tokens`, and `tokens.question_characters` from `len(question)`. `_answer_with_context` records model generation and validation/execution events; execution events record elapsed duration, status, column/row counts on success (no result rows), and errors on failure. Regression coverage: `test_retrieval_trace_records_measured_duration_and_estimates`, `test_empty_question_and_empty_schema_are_clarified_and_redacted`, `test_retrieval_trace_redacts_sensitive_question_text`, plus success/error execution assertions in `test_query_entrypoint_uses_retrieved_catalog_and_approved_join` and `test_unapproved_join_is_rejected_at_query_boundary`. | PARTIAL | Retrieval duration covers only schema retrieval; estimated tokens are a character-based schema estimate and question length is characters, not tokenizer usage. Local retrieval cost is unavailable. Other workflow stages are not comprehensively instrumented, and trace persistence is local JSON without distributed/access-controlled storage. |
| OPS-9 feedback/correction | `FeedbackStore` accepts development-only feedback and gates evaluation to development; `test_feedback_is_redacted_development_only_and_requires_dev_evaluation`. | PARTIAL | No scheduled retraining/evaluation pipeline or router/retriever update implementation. |
| Evidence Ledger/Synthesizer/Fact Checker | `src/ledger/evidence.py`, `src/ledger/synthesizer.py`, integrated by `spike.answer`; grade range 0–4, unsupported figures and causal language checks, template fallback; `test_evidence_ledger.py` and integration tests. | PARTIAL | Full analysis narrative and every EVID contract field are BE-1/AN-1 application responsibilities not present in this spike. |
| Synthetic generator and truth plugin | `data_gen/generator.py`, `data_gen/scoring.py`; deterministic seeds/config, exact scale, planted features/traps, plugin hook, separate scoring truth; `test_same_seed_has_identical_database_hash_and_manifest`, `test_generator_plants_required_edges_and_keeps_truth_outside_warehouse`, `test_plant_plugin_records_every_added_fact`. | PARTIAL | Ground-truth path separation is not enforced by OS/process sandbox; some edge cases are represented as summary labels rather than independently scored scenarios. |
| DATA-5 snapshots | `generate_snapshot_pair`; `test_snapshot_pair_has_distinct_seeds_and_injection_settings`. | PASS | — |
| DATA-6 split management | `data_gen/splits.py::QuestionSplitStore`; unique IDs, immutable development file plus separate `.heldout` file, and held-out role gate; `test_heldout_question_access_is_scoring_only_and_immutable`. | PARTIAL | Files share workspace/user ACLs; `role="scoring"` is not an OS-enforced process boundary; no externally locked question set exists. |
| DATA-1 three data layers | Spider benchmark files and synthetic generation are present; UCI Online Retail II is recorded as a source/license-verified development candidate. | BLOCKED for transactional intake | Candidate contains customer identifiers and is not downloaded; privacy review and reproducible intake/hash are required before treating the third layer as present. |
| DATA-7 provenance | `data_gen/provenance.py` validates required source/license/split/layer fields, optional citation/DOI/intake state, and deterministic directory SHA-256; Spider 1.0 snapshot hash and UCI candidate are in `data/provenance.json`; provenance tests cover hash stability. | PARTIAL | Spider source/license/snapshot now recorded; upstream package revision/date remains unknown. UCI candidate is not ingested and has no data-file hash. |
| DATA-8 final leakage gate | `data_gen/evaluation.py::run_final_evaluation` checks Golden Store before scoring; `test_final_evaluation_checks_leakage_before_calling_scorer`. | PARTIAL | Local caller boundary only, not connected to a separate locked evaluation service. |
| DATA-9 scoring-only truth | Generator writes truth manifests separately from the warehouse and public manifest; question splits now store held-out rows separately; negative access tests and final leakage-before-scorer test pass. | BLOCKED | Same-user filesystem access is not restricted to scoring code. A separate OS account/service identity and protected storage are unavailable here. |
| Deployment/secrets | `.env` is ignored by `.gitignore`; `env.example` is the template; code does not print connection secrets. | BLOCKED | No public web application/hosting deployment or hosting decision is implemented in this Python workspace. No secret scan hook or complete credential audit was run. |

### Trust-layer interface requirements

| Requirement | Implementation and evidence | Status | Remaining work |
|---|---|---|---|
| EVID-2 Evidence Ledger claim IDs, query/module links and grades | `src/ledger/evidence.py::EvidenceLedger`; query path attaches query ID `Q1` and grade; checker rejects linked records with missing/invalid grade; `test_supported_and_unsupported_causal_and_numeric_claims_include_spans`, `test_ledger_requires_evidence_reference_and_synthesizer_uses_fallback`, `test_fact_checker_requires_linked_valid_grade_for_numeric_claims`. | PARTIAL | Query IDs are currently a single local constant; module artifact links and full app-level claim linkage are not integrated. |
| EVID-3 Ledger-only synthesis and no new figures | `src/ledger/synthesizer.py::Synthesizer`; deterministic template fallback and fact check; `test_ledger_requires_evidence_reference_and_synthesizer_uses_fallback`. | PARTIAL | Full narrative synthesis is not wired into a deployed answer workflow. |
| EVID-4 number/date and causal wording check | `FactChecker.verify` checks numeric claims, ISO/US numeric/common English dates, grade-4 causal wording and limits; `test_all_causal_phrases_require_grade_four_and_attached_limits`, `test_number_words_ranges_percentages_units_and_thousands_separators`, `test_fact_checker_rejects_unsupported_dates_and_accepts_equivalent_formats`. | PARTIAL | Other date formats and production narrative formats need broader evaluation; actual analysis path absent. |
| EVID-5 template fallback | `EvidenceLedger.render` and `Synthesizer.synthesize` fallback tested by `test_ledger_requires_evidence_reference_and_synthesizer_uses_fallback`. | PASS | — |
| E5 causal-boundary note | Evidence rendering appends the canonical note; checker requires it for driver analysis; `test_supported_and_unsupported_causal_and_numeric_claims_include_spans`, `test_e5_note_check_is_case_insensitive_but_still_mandatory`. | PARTIAL | AN-1 driver-analysis outputs are not connected to this query spike. |

### Shared safety gates

| Requirement | Evidence in this workspace | Status |
|---|---|---|
| SAFE-1 query allowlist | `src/spike.py::validate/execute`; retrieved schema allowlist and approved join boundary; integration test rejects unapproved joins before execution. | PARTIAL — only the SQLite spike path is covered, not the full BE-1 application. |
| SAFE-2 read-only execution | SQLite URI `mode=ro`, query-only connection, write rejection in `src/spike.py`; existing tests exercise read-only connection. | PARTIAL — connector coverage and full application boundary absent. |
| SAFE-3 numeric claims | `EvidenceLedger`, `Synthesizer`, `FactChecker`; adversarial ledger tests. | PARTIAL — result rows are represented as claims, but full production answer envelope is absent. |
| SAFE-4 injection | Prompt instructs database/question text be treated as data; SQL validation is code-owned. | PARTIAL — no complete injection corpus/guard at all ingress points. |
| SAFE-5 sensitive data | Canary excluded from query prompt and persisted trace; profile/index/artifact redaction tests. | PARTIAL — bounded detection; no exhaustive complete-storage scan. |
| SAFE-6 fail closed | Retrieval clarifies on empty/unmatched/over-budget schema; validator blocks unsupported schema/joins. | PARTIAL — confidence calibration is incomplete and broader refusal cases lack evidence. |
| SAFE-7 secrets | `.env` and `.env.*` ignored while `.env.example` remains eligible; `.env` was not read. | PARTIAL — no secret scan hook, no Git metadata, and no independent repository-history scan. |
| SAFE-8 model boundary | Validator and ledger are deterministic and do not import an LLM client; fake LLM tests cover query generation. | PARTIAL — architecture-wide checks across BE-1/AN-1 modules are outside this project slice. |

## Query path and validation evidence

`src/spike.py::answer` builds/loads the onboarding artifacts, asks
`CatalogAPI`/`SchemaRetriever` for a pruned schema and approved joins, puts
profile warnings and value matches into the bounded prompt, and sends that
context to the existing LLM gateway. The SQL validator checks retrieved table
and column allowlists and approved join key pairs before read-only execution.
The integration suite covers the path, unapproved join rejection, a sensitive
canary, profile warning delivery, value confidence/clarification and the
context budget.

Historical local verification before the latest refresh and recovery changes:

```text
python -m pytest -v -p no:cacheprovider
51 collected; 50 passed, 1 skipped (live LLM test), 0 failed.
```

Targeted trace and store suite: `python -m pytest -v -p no:cacheprovider
tests\\test_query_knowledge_integration.py tests\\test_trust_stores.py` — 15
passed, 0 failed.

```text
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; 101 estimated schema tokens;
retrieval mode keyword_only_dense_unavailable; SQL returned 600;
2 trace events; temporary data removed.
```

## Current continuation verification (2026-10-29)

```text
python -m pytest -v -p no:cacheprovider
55 collected; 54 passed, 1 skipped, 0 failed; exit code 0.
```

The only skip is `tests/test_live_llm.py:11`: live LLM testing is opt-in and
requires `LLM_API_KEY` and `LLM_BASE_URL`. No live call was made.

The latest complete suite was rerun after adding deterministic retrieval
evaluation: 55 collected, 54 passed, 1 skipped, 0 failed; exit code 0. The
latest focused privacy/retrieval/trust/ledger/generator command passed 50 tests.
The affected retrieval/integration module passed 12 tests after the new fixture.

```text
python -m pytest -v -p no:cacheprovider -rs tests/test_privacy.py tests/test_query_knowledge_integration.py tests/test_join_governance.py tests/test_pipeline_trust.py tests/test_trust_stores.py tests/test_evidence_ledger.py tests/test_generator.py
49 passed; 0 skipped; 0 failed; exit code 0.
```

The targeted refresh/recovery/governance command
`python -m pytest -v -p no:cacheprovider tests/test_pipeline_trust.py tests/test_query_knowledge_integration.py tests/test_join_governance.py`
passed 16 tests. Both defects were first reproduced by regression tests; one
additional implementation attempt was corrected after discovering that
`sqlite3.Row` object representations were nondeterministic. The final focused
same-count refresh and recovery tests passed individually.

`python -m compileall -q src data_gen tests` exited 0. `python -m src.onboarding.demo` exited 0: 50 tables, self-test passed, estimated
context 101 tokens, keyword-only retrieval, query returned 600, 3 trace events,
temporary data removed.

Fresh isolated build sweep (generator plus onboarding build, seeds 157/307/607;
temporary warehouses/catalogs/truth/provenance): 50 tables: generator 0.051 s,
build 1.119 s, self-test passed; 200 tables: 0.025 s / 1.880 s, passed; 500
tables: 0.128 s / 5.552 s, passed. These are local one-run timings, not SLAs or
cost measurements. The signatures change adds a content scan on source-file
change; unchanged source hashes reuse prior table signatures.

The dense and cross-encoder adapters are optional interfaces only. No model or
vector dependency was installed. The demo's retrieval is explicitly
keyword-only; its estimate is not a tokenizer measurement. No live LLM test was
run. Scale builds were previously measured in temporary storage at about 1.12s,
1.78s and 3.14s for 50, 200 and 500 tables respectively on the current
environment; these are single local observations, not a cost/SLA benchmark.

## Workspace and operational limitations

This workspace has no `.git` metadata, and neither the nested reference copy
nor the adjacent locations inspected provide a safe repository root. Git
history, tracked modifications, staging and untracked status therefore cannot
be verified. The nested `Data_Scientist_Agent` copy is reference-only. The
current implementation remains a local SQLite/Python spike: it does not
provide a deployed web app, scheduler, authenticated review workflow, production
dense/vector retrieval, or OS-enforced held-out secrecy. Those limitations
prevent declaring the whole 4.4 package complete.

## Continuation verification (2026-10-29)

The historical evidence above was rerun before this continuation. The current
trust-layer change closes two checker gaps: dates were not compared with ledger
dates, and manually loaded linked claims without a valid 0–4 grade could
support narrative text. `FactChecker` now parses ISO, US numeric, and common
English month-name dates and requires exact calendar-date support; date
components are excluded from numeric checks. Evidence claims must have a valid
grade. The required E5 note check accepts case differences while synthesis
continues to emit the canonical note. Regression tests:
`test_fact_checker_rejects_unsupported_dates_and_accepts_equivalent_formats`,
`test_fact_checker_requires_linked_valid_grade_for_numeric_claims`, and
`test_e5_note_check_is_case_insensitive_but_still_mandatory`.

Actual validation after the change:

```text
python -m pytest -v -p no:cacheprovider tests/test_evidence_ledger.py
15 passed, 0 failed.
python -m pytest -v -p no:cacheprovider tests/test_evidence_ledger.py tests/test_privacy.py tests/test_trust_stores.py tests/test_join_governance.py tests/test_query_knowledge_integration.py
42 passed, 0 failed.
python -m pytest -v -p no:cacheprovider
59 collected; 58 passed, 1 skipped (opt-in live LLM), 0 failed.
python -m pytest -v -p no:cacheprovider tests/test_retrieval_eval.py
2 passed; keyword fixture and injected hybrid adapter-path test passed.
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; query returned 600; 3 trace events;
temporary data removed.
```

Fresh temporary scale verification regenerated and onboarded all three sizes;
all reports had passing self-tests. End-to-end local elapsed times (generator
plus onboarding, one run each) were 6.337 s for 50 tables, 6.845 s for 200,
and 4.080 s for 500. These are noisy local observations, not benchmarks or
cost/SLA evidence. Reports remained `needs_review` because generated warehouses
intentionally raise human review items.

The work remains PARTIAL. Dense indexing/model-backed reranking, authenticated
held-out isolation, public transactional data provenance, production job/review
services, cross-owner application integration, and deployment are not supplied
by this local workspace. See the acceptance matrix for per-requirement status
and executable evidence.

## BE-2 continuation audit and verification (2026-10-29)

The incoming baseline was verified first: `python -m pytest -v -p
no:cacheprovider` collected 59 tests, 58 passed, 1 live-LLM test skipped, 0
failed.

### Dense retrieval delivered locally

Added `src/knowledge/dense_index.py`, a dependency-free signed word/character
n-gram vector encoder and persisted index. It is genuine vector retrieval with
cosine scoring and keyword RRF, but it is a lexical feature-hashing baseline,
not a learned semantic embedding model. The index records the backend and
encoder version, dimensions, corpus SHA-256 and content-derived index version.
The onboarding `dense_index` stage builds only from fully masked/redacted
documents, persists vectors to `index_build.json` and `dense_index.json`, retries
on rebuild, and reuses vectors whose indexed document is unchanged. Corrupt,
stale, or incomplete payloads fail closed to keyword-only mode. No package was
installed; NumPy happened to be available but the implementation uses only the
standard library. No model weights, vector service, or cross-encoder are
available, so learned semantics and cross-encoder reranking remain open.

`tests/test_retrieval_eval.py` uses a fixed three-table catalog and six
questions: three exact and three controlled misspellings. Measured on that
small deterministic fixture, hybrid recall@1 = 1.00 and MRR = 1.00; keyword
only recall@1 = 0.50 and MRR = 0.50. It also verifies persisted versions,
deterministic rebuild, unchanged-vector reuse after an invoice-table edit, and
safe fallback/repair after corrupting the vector artifact. This is fixture
evidence, not a production corpus result.

### Held-out handling, provenance, and boundaries

`QuestionSplitStore` now writes development and held-out cases to separate
files, retains immutable split checks, and requires the scoring role before
reading held-out rows. `GoldenStore.promote` and approval now require a non-empty
held-out question set; only development rows can be approved or returned by
nearest-neighbor retrieval. `run_final_evaluation` already checks leakage
before invoking its scorer. Tests cover unauthorized split reads, file
separation, held-out promotion/retrieval rejection, and scorer-not-called on a
leak. These remain Python-level controls: this Windows workspace has no
separate scoring account, service identity, protected store, or ACL policy, so
same-user filesystem access to `.heldout` and truth manifests is still
possible. No OS-enforced isolation is claimed.

The official UCI Online Retail II source page identifies a 1,067,371-row
transaction dataset and CC BY 4.0 terms with attribution. A development-only
candidate record is in `data/provenance.json`, including the citation and DOI.
The workbook was not downloaded: its CustomerID field requires a privacy
assessment before intake, and no local hash is therefore available. The Spider
1.0 official project page confirms the benchmark and CC BY-SA 4.0 terms. The
local development snapshot (393 files, 883,928,091 bytes) now has reproducible
aggregate SHA-256 `808f8d66cb8ab5d066af3934047cc02bde555db28d4149310984f805af90a844`
and citation/DOI in `data/provenance.json`; upstream package revision/date is
not embedded in this workspace, so the local file hash is the reproducibility
anchor.

Production BE-2 deliverables still open: authenticated onboarding/review API,
identity-backed reviewer authorization, a scheduled refresh runner, service
database/distributed persistence, and deployment. Existing Python CLI, local
JSON audit, approval functions, refresh implementation and job recovery remain
the supported local interfaces. BE-1 owns API routing/auth integration; FE-1
owns onboarding/review screens; AN-1 owns planted analysis truth/scoring
content; deployment infrastructure and a scoring identity are not provisioned
in this workspace. No external deployment or secrets were attempted.

## Product.md BE-2 service facade continuation (2026-10-29)

Product.md assigns BE-2 Python service functions behind onboarding, refresh,
join/sensitive review, Golden candidate review, and Registry review routes;
BE-1 owns authenticated HTTP routing and FE-1 owns review screens. Added
`src/onboarding/service.py::OnboardingService` as that local service boundary.
It persists job-to-source/output mappings, runs SQLite builds, reads
status/report artifacts, refreshes a job, lists join and sensitive review
items, records named decisions and rebuilds to publish them, and exposes
pending Golden and metric decisions through existing stores. The interface
contract is in `contracts/knowledge_api.md`.

Validation:

```text
python -m pytest -v -p no:cacheprovider tests/test_onboarding_service.py
3 passed.
python -m pytest -v -p no:cacheprovider tests/test_onboarding_service.py tests/test_pipeline_trust.py tests/test_join_governance.py tests/test_trust_stores.py
16 passed.
python -m pytest -v -p no:cacheprovider
66 collected; 65 passed, 1 opt-in live-LLM test skipped, 0 failed.
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; hybrid query returned 600; 3 trace events.
```

Fresh temporary scale sweep (seed 7, generator then onboarding): 50 tables in
1.271 s with 248 dense vectors; 200 in 2.332 s with 998 vectors; 500 in
4.565 s with 2,498 vectors. All self-tests passed. Times are single-run local
observations, not SLA evidence.

This closes the local Python service-interface gap with executable tests; it
does not complete production integration. `start()` is synchronous,
authentication/authorization must be enforced by BE-1 before review methods,
local JSON stores are not a multi-process database, FE-1 screens are external,
and no scheduled refresh worker or deployment target is provisioned. Those
production integrations remain PARTIAL/BLOCKED pending owners and environment.

### Actual verification after these changes

```text
python -m pytest -v -p no:cacheprovider tests/test_retrieval_eval.py
3 passed.
python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py tests/test_generator.py::test_heldout_question_access_is_scoring_only_and_immutable tests/test_privacy.py::test_pipeline_masks_canary_from_all_json_artifacts tests/test_retrieval_eval.py
12 passed.
python -m pytest -v -p no:cacheprovider
62 collected; 61 passed, 1 opt-in live-LLM test skipped, 0 failed.
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; query returned 600; hybrid retrieval;
3 trace events; temporary data removed.
```

Fresh temporary generation plus onboarding on seed 7 passed self-tests at 50,
200, and 500 tables. Final elapsed times were 1.315 s, 2.381 s, and 4.589 s. Dense
vector counts were 248, 998, and 2,498; every build reported hybrid retrieval.
These are single local observations, not cost/SLA benchmarks. An initial demo
run hit the trace-count assertion; instrumented inspection found three events,
and the exact demo command then passed on rerun. No code workaround was needed.

## BE-2 operations hardening continuation (2026-10-29)

This section supersedes the earlier synchronous-job and no-scheduler notes.
`OnboardingService` now uses `service.sqlite3` (SQLite WAL) for durable job and
schedule state, with a bounded worker pool for asynchronous initial builds and
refreshes. It supports persisted interval schedules, due-job queueing,
`src.onboarding.worker` as a supervised polling process, explicit stale-job
lease recovery, and retry through pipeline stage recovery. Review methods now
queue and wait for the publication rebuild. Local JSON Metric, Golden, Trace,
Cache, Action and Feedback store mutations use process-safe file locks around
atomic file replacement. Active jobs refresh their `updated_at` heartbeat
every 10 seconds so lease recovery can distinguish long-running work from
stale jobs.

Evidence from this run:

```text
python -m pytest -v -p no:cacheprovider tests/test_onboarding_service.py
6 passed.
python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py tests/test_onboarding_service.py tests/test_query_knowledge_integration.py
24 passed.
python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py::test_concurrent_metric_proposals_keep_every_revision
1 passed (20 concurrent proposals retained revisions 1..20).
python -m pytest -v -p no:cacheprovider
70 collected; 69 passed; 1 opt-in live-LLM test skipped; 0 failed.
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; hybrid query returned 600; 3 trace events.
python -m src.onboarding.worker --help
exit 0.
```

Fresh temporary scale run, seed 7: 50 tables / 248 vectors / 1.321 s;
200 / 998 / 2.440 s; 500 / 2,498 / 4.710 s. All self-tests passed. These
single-run times are not SLA evidence.

Still PARTIAL/BLOCKED: no learned embedding package or model-weight cache is
installed (package presence checked without installing anything); dense
vectors remain hashed lexical features. Same-user held-out file access cannot
be prevented without a separate scoring account/service and protected
ACL/storage. UCI transactional intake remains pending privacy review. This is
a local Python package, not the complete authenticated web application; no
hosting target or deployment credentials were provisioned. No secrets were
read and no public deployment was attempted.

### Cross-process store verification (2026-10-29)

Added a Windows process-pool regression test for Metric Registry updates. Twelve
concurrent proposals from four separate processes retained versions 1 through
12 in the persisted file, exercising the OS lock-file path rather than only
thread synchronization.

```text
python -m pytest -v -p no:cacheprovider tests/test_trust_stores.py::test_cross_process_metric_proposals_keep_every_revision
1 passed.
python -m pytest -v -p no:cacheprovider
71 collected; 70 passed; 1 opt-in live-LLM test skipped; 0 failed.
```

This strengthens verification of local concurrent store writes. It does not
replace a managed database, backup/retention controls, or production
multi-host persistence.

## Open-source retrieval and transactional intake continuation (2026-10-29)

Selected pinned open-source models for the optional learned path:

- Embeddings: `sentence-transformers/all-MiniLM-L6-v2`, Apache-2.0, pinned to
  revision `2a7cca6ad7605f3183bce07f677bda658059bbe9`.
- Reranking: `cross-encoder/ms-marco-MiniLM-L6-v2`, Apache-2.0, pinned to
  revision `f130f2b05c9b70e021b4833afe43c6993e2c7563`.
- `requirements-embeddings.txt` pins the optional Sentence Transformers
  runtime. `python -m src.knowledge.model_assets` downloads only these exact
  public revisions after explicit operator invocation; onboarding never
  downloads models implicitly. `build --learned-embeddings` and the async
  onboarding service accept the learned encoder. Index metadata records model
  identity/revision and checks compatibility before query-time use.

Environment evidence: Python 3.13.2 has none of `sentence_transformers`,
`torch`, `huggingface_hub`, or `openpyxl`, and the configured model cache does
not exist. Thus real model weights, learned-model retrieval scores, and model
runtime performance have not been tested here. Deterministic adapter/persisted
index tests use fixtures and do not count as real model evaluation. Existing
measured retrieval results remain the six-case hashed lexical fixture only.

Added `data_gen/transactional_intake.py`, an opt-in local UCI Online Retail II
XLSX importer. It refuses overwrite, requires a non-empty privacy-review
reference, drops `CustomerID`, replaces source invoice IDs with deterministic
encounter-order transaction IDs, records source/output SHA-256 and provenance,
and preserves duplicate line items. It never downloads data. Tests use synthetic
rows and verify identifier removal, duplicates, cancellation mapping, invalid
row rejection, required headers and overwrite refusal. No real source file has
been downloaded or ingested, and the reference parameter does not verify an
organizational approval; DATA-1 remains pending the actual privacy review,
source artifact, and optional XLSX runtime.
The optional `openpyxl==3.1.5` reader is declared in
`requirements-uci-intake.txt` but was not installed.

Actual validation in this continuation:

```text
python -m pytest -v -p no:cacheprovider tests/test_transactional_intake.py tests/test_retrieval_eval.py
8 passed.
python -m pytest -v -p no:cacheprovider
76 collected; 75 passed; 1 opt-in live-LLM test skipped; 0 failed.
python -m src.knowledge.model_assets --help
exit 0 (explicit-download interface available; weights not fetched).
python -m src.onboarding build --help
exit 0 (`--learned-embeddings` option shown).
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; query result 600; hybrid lexical mode; 3 trace events.
seed-7 temporary scale sweep
50 tables / 248 vectors / 1.314 s; 200 / 998 / 2.458 s; 500 / 2,498 / 4.790 s; all self-tests passed.
```

BE-2 remains PARTIALLY COMPLETE. Learned-model retrieval requires an approved
dependency/model-cache setup with network access or pre-provisioned weights,
followed by a real held-out quality evaluation. OS-enforced held-out secrecy
requires an administrator-provisioned scoring account and protected storage.
Transactional intake requires completed privacy review and the official source
file. Production API authentication, hosted scheduling, deployment, and
secrets integration require the BE-1 service/auth owner and provisioned
deployment infrastructure. No dependency was installed and no public deploy
was attempted.

## Publication-consistency continuation (2026-10-29)

The 4.4 idempotent/resumable-build row was the highest-priority unfinished
criterion completable without network, downloads, or package installation. The
catalog version is now written into `index_build.json`, and `published.json` is
written atomically last with SHA-256 hashes for the build artifacts. `CatalogAPI`
verifies the catalog and index against that manifest and raises
`CatalogIntegrityError`; `SchemaRetriever` fails closed to clarification rather
than serving a partially published generation. A subprocess test kills a refresh
after the index write but before the catalog write, verifies the reader fails
closed, then verifies a normal rerun repairs and republishes the build.

Actual validation:

```text
python -m pytest -v -p no:cacheprovider tests/test_pipeline_trust.py
4 passed.

python -m pytest -v -p no:cacheprovider tests/test_pipeline_trust.py tests/test_query_knowledge_integration.py tests/test_retrieval_eval.py tests/test_join_governance.py tests/test_onboarding_service.py tests/test_privacy.py
36 passed.

python -m pytest -p no:cacheprovider
77 passed, 1 skipped, 0 failed; exit code 0.
```

The skip remains the opt-in live-LLM test. Non-query artifacts are not swapped
by a single filesystem transaction, but readers only accept the committed
manifest generation. No network access, downloads, package installation, or
Cadra submission was performed.

## Learned retrieval end-to-end integration continuation (2026-10-29)

Closed a local integration gap: `spike.answer()` now builds the catalog with
the same injected embedder it uses at query time. `python -m src.spike
--learned-retrieval` explicitly loads both pinned models from local cache and
uses them for schema retrieval; ordinary runs remain offline and deterministic.
If cross-encoder inference throws, retrieval retains the original keyword+dense
RRF order, labels the result `hybrid_reranker_fallback`, and exposes a warning
instead of failing the query.

Added `src.knowledge.evaluate_retrieval`, a fixed 12-query schema paraphrase
evaluation that reports recall@1 and MRR for a selected local model. Its
interface and metric calculation pass against a fixture encoder, and an
integration regression proves that query-time catalog rebuilding persists and
uses the matching encoder version and recovers from reranker failure. These
fixture tests verify integration mechanics only; they are not model quality
evidence.

Verified the workspace virtual environment has `huggingface_hub`, but no
`sentence_transformers`, `torch`, or ONNX runtime. No cached snapshots exist
for either pinned model, and the configured model-cache variables are unset.
The previous outbound HTTPS request was denied by the environment, so no
download or installation was attempted. Actual learned embedding/reranking and
the 12-query measured results remain blocked on network access or provisioned
weights plus the optional runtime.

Validation from this continuation:

```text
python -m pytest -v -p no:cacheprovider tests/test_retrieval_eval.py::test_reproducible_learned_model_evaluation_harness_reports_metrics tests/test_query_knowledge_integration.py::test_query_entrypoint_builds_with_learned_encoder_and_recovers_reranker_failure
2 passed.
python -m src.knowledge.evaluate_retrieval --help
exit 0.
python -m pytest -v -p no:cacheprovider
88 collected; 87 passed; 1 opt-in live-LLM test skipped; 0 failed.
```

GRD-4 implementation is improved but remains **PARTIAL** until actual pinned
model inference and measured evaluation pass. No model download or dependency
installation was attempted.

## BE-2-only implementation continuation (2026-10-29)

Completed additional local deliverables:

- Added and loaded three versioned synthetic-demo Metric Registry seed proposals
  (`demo_order_count`, `demo_order_revenue`, and
  `demo_monthly_region_revenue`). They remain `proposed`, never auto-approved.
  The seed-7 reconciliation values were queried from the generated warehouse;
  `seed_registry()` is idempotent by stable seed ID.
- Added `data_gen.quality_checks` with 17 independent checks for dataset hash,
  cryptic/distractor tables, stale/duplicate archive rows, messy values, missing
  foreign keys, soft deletes, test orders, merged customers, late events,
  truncated snapshots, unanswerable fields, and private SQL-trap reconciliation.
  Generator version 5 truth files now include the warehouse SHA-256; the loader
  remains backward-compatible with existing v4 truth files. Audit passed 17/17
  for 50, 200 and 500 table seed-7 development snapshots and both snapshots in
  a 50-table pair. A negative mutation test confirmed a removed defect and
  changed source hash are detected.
- Expanded Fact Checker date parsing to ISO with slash/dot separators,
  compact YYYYMMDD, common numeric day/month formats, month-name forms,
  ordinals, and abbreviated September. Tests cover equivalent dates and reject
  unsupported dates.
- Replaced the constant ledger query ID with the actual run UUID, linking
  claims to the emitted query run. The existing `artifact` linkage remains the
  BE-2 interface for analyst module artifacts.

Actual validation:

```text
python -m pytest -v -p no:cacheprovider tests/test_metric_seeds.py tests/test_generator_quality.py tests/test_generator.py tests/test_evidence_ledger.py tests/test_query_knowledge_integration.py
48 passed.
python -m pytest -v -p no:cacheprovider
99 collected; 98 passed; 1 opt-in live-LLM test skipped; 0 failed.
python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; result 600; 3 trace events.
scale_report seed 7
50/200/500 tables; 248/998/2,498 hashed vectors; self-tests passed; onboarding 1.376/2.539/4.822 seconds.
quality audit
17/17 passed at 50, 200, 500 tables and both 50-table snapshot-pair members.
```

Still incomplete / blocked for BE-2:

- Real learned model execution and measured model metrics: runtime and pinned
  snapshots are absent; prior outbound HTTPS was denied, so download was not
  retried. Fixture evaluation validates only the harness.
- Third transactional data source: no UCI workbook is present; intake remains
  pending an actual organizational privacy approval and reviewed source file.
- Deployment: no hosting target or environment/secret provisioning exists.
- Held-out enforcement: generated truth is hash-bound and split reads are
  caller-gated, but OS access isolation needs a scoring service identity and
  protected storage.
- Metric seeds are synthetic-demo proposals; business owner review is still
  required before approval or use against another warehouse.
- Analyst artifacts can be linked through the ledger interface, but actual
  module-output wiring belongs to AN-1. BE-1 must pass authenticated run IDs
  through its production orchestration interface.

The full BE-2 assignment remains **PARTIALLY COMPLETE**; these results do not
claim completion of dependencies requiring model assets, privacy approval,
separate OS identity, or deployment infrastructure.

## Existing implementation audit and local improvement pass (2026-10-29)

Reviewed this workspace's progress/acceptance records, Product §4.4, the
BE-2-owned GRD/MET/DATA requirements, the onboarding/retrieval/store/intake/
scoring/gateway code, the relevant tests and fixtures, the demo, and the scale
runner. The nested `Data_Scientist_Agent` reference copy was read only.

### Prioritized review findings and fixes

| Priority | Component and issue | Change and verification |
|---|---|---|
| P0 | `SchemaRetriever` could silently lose the reason for unavailable learned weights, and runtime encoder errors could abort query retrieval. Retrieval modes also called hashed and learned paths simply `hybrid`. | Added immutable 40-character model-pin validation, paired ID/revision environment overrides, exact-cache offline errors, explicit downloader errors, deterministic hashed/keyword restart after encoder failure, and modes that distinguish hashed, learned, reranked and fallback behavior. Invalid vectors/non-finite reranker scores fail into the documented fallback. Added tests in `test_retrieval_eval.py` and `test_query_knowledge_integration.py`. |
| P0 | `MetricRegistry` treated a non-empty reviewer string as sufficient authority and accepted malformed definitions or unreasoned rejection. | Registry decisions now deny unless a host-supplied authorization callback returns literal `True`; decisions require an explicit bool, a named identity, a rejection reason, and valid proposal shapes. Notes are bounded and redacted; status/history changes remain under the process lock. `OnboardingService` accepts the host policy. Tests cover missing/unauthorized identities, weak truthy policies, duplicate/invalid transitions, and note redaction. All existing seed records remain `proposed`. |
| P0 | Held-out access used the forgeable string `role="scoring"`; approved callers could also write held-out questions to shared development stores from the final scorer callback. | Replaced role-string access with an injected deny-by-default `ScoringAccessPolicy`; truth loading, split reads and final evaluation require a principal plus policy. Final scoring runs in a held-out context that blocks mutation of metric, Golden, Trace, cache, action, feedback, split, generator and provenance stores. Negative tests verify a spoofed role/principal cannot read and scorer callbacks cannot write to those stores. This is an application boundary only; direct filesystem access remains possible. |
| P1 | Transactional intake accepted any non-empty privacy reference, materialized the full workbook sheet in memory, and did not require complete intake provenance. | Added matching approval-record validation (status, reference, dataset scope, reviewer, ISO timestamp), strict UCI source/license/permitted-use/citation/hash checks, duplicate-header and row-value checks, non-empty valid-row enforcement, and streaming sheet import. Provenance publication now uses atomic replacement. Tests cover absent workbook, missing/mismatched approval evidence, invalid provenance, malformed rows, and overwrite protection. The record validator checks fields but cannot authenticate the issuing organization. |
| P1 | Generator provenance omitted the warehouse digest even though it was already computed; stricter provenance validation exposed that defect. | Synthetic records now store the actual database SHA-256 and generator version. The failure was reproduced across generator/metric-seed tests, corrected, and retested. |
| P1 | LLM environment values were parsed without range/URL validation; deployment readiness had no local diagnostic. | Added stable non-sensitive configuration errors, retry/timeout bounds, HTTPS-only remote URLs (loopback HTTP allowed), placeholder-key rejection, and `python -m src.onboarding health --root .`. The health output distinguishes core local readiness from absent optional model runtime/weights, missing LLM configuration, and unconfigured scoring principals. Added unit tests and `contracts/BE2_DEPLOYMENT.md`. |
| P2 | Pattern redaction could theoretically rewrite a UUID trace key when it shared digits with a sensitive value, making persisted events unqueryable. | Trace storage now preserves only canonical UUID correlation IDs while continuing to redact event content. A deterministic overlapping-digit regression test reproduces and verifies the case. The demo's first concurrent invocation had reported too few trace events; an isolated rerun passed after the correlation-key guard. |

Other reviewed gaps remain: dense vectors are local signed n-gram feature hashing by default; confidence anchors and retrieval fixtures are small and not production-calibrated; token counts are estimates; profile/masking and self-test checks are bounded; stores are local JSON/SQLite; and no authenticated HTTP application or analyst-module integration is present in this BE-2 workspace. These limits are not hidden by passing unit tests.

### Actual verification

Baseline before code changes:

```text
python -m pytest -v -p no:cacheprovider
99 collected; 98 passed; 1 opt-in live-LLM test skipped; 0 failed.
```

During implementation, the recursive cycle recorded these intermediate
failures before fixes:

```text
Initial focused batch: 49 collected; 40 passed, 9 failed. Causes: the new
fallback fixture had an intentional model/index pin mismatch; an old metric
transition assertion lacked the now-required rejection reason; synthetic
generator provenance had no digest; those generator failures also affected
metric-seed reconciliation.
Retest: 13 passed, 0 failed after matching the fixture encoder, supplying the
review reason, and writing the generator's existing database hash to provenance.

Next focused batch: 59 collected; 55 passed, 4 failed. Causes: legacy tests
expected the old ambiguous `hybrid` mode, a test signature omitted pytest's
monkeypatch fixture, and timeout validation ran only when constructing a real
client. The same run also showed unavailable-model warnings were dropped when
retrieval clarified early.
After fixes, the isolated warning regression passed; the combined affected
suite then passed 65 tests.

First post-change full suite: 120 collected; 118 passed, 1 skipped, 1 failed.
The remaining failure was the service test relying on reviewer-name-only
approval. It was changed to inject a test host policy; the focused service test
passed, and the later final full suite passed.

One demo invocation in parallel validation exited 1 because it found fewer
than two events for its run. Isolated reruns passed with 3 events. Trace storage
now preserves canonical UUID correlation IDs across overlapping PII redaction,
covered by a deterministic regression. The parallel-only demo failure was not
reproduced after that fix.
```

These failures were not skipped or hidden; affected tests and the final full
suite were rerun.

Final commands and outcomes:

```text
python -m pytest -v -p no:cacheprovider
122 collected; 121 passed; 1 opt-in live-LLM test skipped; 0 failed (32.48 s).

python -m pytest -v -p no:cacheprovider tests/test_privacy.py tests/test_transactional_intake.py tests/test_trust_stores.py tests/test_generator.py tests/test_generator_quality.py tests/test_metric_seeds.py
40 passed; 0 failed.

python -m src.onboarding health --root .
exit 0; core local checks ready. Both model pins validate, but runtime and weights are absent. LLM is not configured; no scoring principal is configured. The command explicitly states it does not validate network, identity provider, ACL or deployment.

python -m src.onboarding.demo
exit 0; 50 tables; self-test passed; retrieved-data query returned 600; 3 trace events; retrieval mode `hybrid_hashed`; temporary data removed.

python -m src.onboarding.scale_report --sizes 50 200 500
exit 0; seed 7; self-tests passed; 248 / 998 / 2,498 hashed vectors; generation 0.021 / 0.027 / 0.045 seconds; onboarding 1.340 / 2.432 / 4.682 seconds. Report refreshed in `BE2_SCALE_REPORT.md`; one local run, not an SLA or cost result.

python -m src.onboarding review --help
exit 0; reviewer argument is required.

python -m src.knowledge.model_assets --help
exit 0; explicit pinned-model provisioning interface shown; no model download was attempted in this pass.
```

The 12-case learned-evaluation harness is still fixture-tested only. No model
weights were loaded and no genuine learned-model retrieval metrics were
produced. The live-LLM test remains the single intentional opt-in skip.

### Requirements status after this pass

- Retrieval loader/fallback behavior: **implemented and fixture-tested**;
  GRD-4 remains **PARTIAL** until the exact runtime/weights are provisioned and
  a real evaluation is executed. Required next command sequence is documented
  in `contracts/BE2_DEPLOYMENT.md` and `contracts/knowledge_api.md`.
- Metric authorization/audit workflow: **implemented and tested locally**;
  MET-6 remains **PARTIAL** because production identity authentication is not
  available. The three seed metrics remain `proposed`; an authorized business
  reviewer must review definitions and record approve/reject plus reasons.
- UCI intake validation: **implemented and tested on synthetic rows**; DATA-1
  remains **BLOCKED** until the real workbook and organization-provided privacy
  approval record are available and verified. No UCI workbook was ingested.
- Held-out access: **application checks improved and negative-tested**; DATA-9
  remains **BLOCKED** for strong isolation until a separate scoring OS identity,
  protected storage and independent ACL verification are provisioned.
- Startup/readiness: **local readiness command and deployment checklist
  implemented and tested**; deployment remains **BLOCKED** until a target,
  secret manager, authenticated host and operational controls exist.

No approvals, source data, credentials, model outputs, scoring infrastructure,
or public deployment were fabricated or provisioned. No Cadra trace was
submitted. BE-2 remains **PARTIALLY COMPLETE**.
