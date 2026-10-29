# Knowledge API contract

## Current adapter

BE-2 currently targets SQLite warehouses and persists one build under
`artifacts/catalog/`. `python -m data_gen.generator --tables 50 --seed 7` creates
a deterministic development warehouse. `python -m src.onboarding build
--warehouse data/generated/warehouse.sqlite` starts or resumes onboarding.

`job.json` is the progress record. Stage artifacts are JSON files named after
their stage. `catalog.json` binds the metadata catalog, profiles, trust features,
join graph, descriptions and knowledge graph to a `catalog_version`.
`report.json` is the onboarding summary. `review.json` stores human decisions;
rerun `build` after `review` to publish those decisions. The catalog is marked
`needs_review` while suggested sensitive columns or proposed joins await review.

`src.onboarding.service.OnboardingService` implements the local Python service
facade for Product.md sections 5.1/5.7. `start(connection)` and
`refresh(job_id)` enqueue work on a bounded worker pool and return a persisted
`job_id`; `wait(job_id)` is available to local callers and tests. `status()` and
`report()` expose progress and artifacts; `joins()` and `sensitive_columns()`
expose review queues; `decide_review()` records named decisions and waits for
the publication rebuild. Jobs and schedules are stored in `service.sqlite3`
using SQLite WAL. Metric, Golden, Trace, Action, Cache and Feedback JSON updates
use process-safe file locks and atomic replacement. `schedule_refresh()` stores
interval schedules; `python -m src.onboarding.worker --root <service-root>` is
the supervised polling worker. `recover_interrupted_jobs()` expires stale
worker leases explicitly; `retry()` resumes through pipeline stage recovery.
BE-1 must provide authenticated HTTP routing and derive reviewer identity from
its authenticated principal; this local facade does not authenticate callers.
Metric review specifically requires constructing `OnboardingService` with a
`metric_reviewer_authorizer` callback backed by that host identity provider.
The callback must return literal `True`; a reviewer string alone is never
authorization. The local CLI's join/description review requires a reviewer
argument, but it is not an identity provider.

The Python read API is `src.knowledge.catalog_api.CatalogAPI`:

* `tables()` and `schema(table=None)` read catalog metadata.
* `join_edges()` returns approved edges only. Pass `approved_only=False` for
  review and diagnostic use; query generation must use the default.
* `search(query)` performs deterministic keyword lookup.
* `value_lookup(value)` searches the local categorical sample index.

`src.knowledge.stores` provides local JSON implementations of `MetricRegistry`,
`GoldenStore`, `TraceStore`, `CatalogCache` and `ActionLibrary`. Metric proposal
records are schema-validated; decisions include reviewer, timestamp, reason,
revision and status history. Metrics remain proposed until a host-authorized
reviewer decides. Shared development stores reject writes during the local
held-out scoring scope. Golden query promotion requires passing
result checks and human approval; held-out split entries are rejected and
`leakage_check()` compares promoted questions with held-out text. Dataset
licence/provenance records use `data_gen.provenance.register_dataset`.

## Storage and versioning decision

The build persists a keyword index, categorical value index, and local dense
vector index in `index_build.json`. The dense index uses deterministic signed
word and character n-gram feature hashing, stores encoder/corpus/index versions,
and checks vector/corpus digests before use. It reuses unchanged vectors during incremental rebuilds. It is a lexical vector
baseline, not a learned semantic embedding model. Invalid or stale vector
artifacts fail closed to keyword retrieval and are rebuilt with the onboarding
`dense_index` stage. A real embedding model and cross-encoder reranker remain
unconfigured because no model weights or service are available in this
workspace; those versions must be recorded if added.

An optional learned backend is wired through `dense_encoder` in
`build_catalog()`/`OnboardingService` and `embedder` in `SchemaRetriever`.
`src.knowledge.semantic_models` pins Apache-2.0
`sentence-transformers/all-MiniLM-L6-v2` and
`cross-encoder/ms-marco-MiniLM-L6-v2` revisions. Runtime loading is local-only;
`python -m src.knowledge.model_assets` is the explicit public-weight download
step, and `python -m src.onboarding build --learned-embeddings` requires the
embedding model already cached. The current workspace has neither the optional
runtime nor model assets, so only adapter/index fixtures have been tested. No
real learned retrieval or reranking quality claim is made. `spike.answer()`
passes a supplied embedder to both catalog building and retrieval;
`python -m src.spike --learned-retrieval` loads both models from the local cache.
Optional model IDs can be overridden only together with a full lowercase
40-character commit revision using `TEXTTOSQL_EMBEDDING_MODEL_ID` /
`TEXTTOSQL_EMBEDDING_MODEL_REVISION` and the matching `RERANKER` variables.
`TEXTTOSQL_MODEL_CACHE` selects the local cache. Missing pins/weights/runtime
produce explicit errors; an embedding runtime fault restarts with the matching
persisted hashed index when available, otherwise keyword-only retrieval.
Reported retrieval modes distinguish learned, hashed, reranked and fallback
paths. The default CLI answer flow remains the hashed lexical mode. Run
`python -m src.knowledge.evaluate_retrieval` after provisioning the models to
record model-backed Recall@1/MRR on the versioned 12-case synthetic schema
fixture. This is not a production-corpus evaluation. The harness tests in this
workspace use mock adapters; no real metrics exist until real weights are
loaded and the command is executed. Reranker runtime failure falls back to RRF
and is exposed in the result mode/warnings.

Held-out reads now require both a `ScoringAccessPolicy` and an authorized
principal; the old `role="scoring"` string is not accepted. The policy is
application-level only: an authenticated host must supply it from its trusted
principal, while a separate scoring OS account and protected storage remain
necessary to prevent direct file access. `data_gen.transactional_intake`
requires a matching approval record JSON as well as the actual reference; the
record fields are validated but its issuer is not cryptographically
authenticated by this local importer.

Run `python -m src.onboarding health --root .` for local readiness diagnostics.
It does not contact a network, health-check an HTTP service, verify OS ACLs, or
prove production deployment. See `contracts/BE2_DEPLOYMENT.md` for startup and
deployment verification steps.

Warehouse credentials do not belong in this repository. The initial adapter
accepts a local SQLite path and opens it with `mode=ro` plus `query_only`; future
connectors must obtain secrets from environment/secret configuration and expose
the same read interfaces without logging credentials.

SQLite does not retain reliable table update timestamps, so freshness and
historical query usage are reported as unknown until a connector supplies those
signals. Refresh signatures detect DDL, row-count and recognized update-time
changes. A connector with no update timestamp cannot detect same-count row edits
without scanning table contents; such a connector needs a reliable watermark or
a full content comparison before promising complete incremental refresh. In
this SQLite adapter, changed tables are re-profiled while unchanged table
profiles are reused.
