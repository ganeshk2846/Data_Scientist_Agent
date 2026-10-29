# BE-2 Checkpoint

Date: 2026-10-29
Workspace: `C:\Users\messi\OneDrive\Desktop\CADRA\TextToSQL`

## Current State

All requested BE-2 tasks completed in order: **2 → 7 → 10 → 3 → 1**.

- Latest task: description review workflow.
- Acceptance criterion: **4.4.1 Stage 6 — preserve descriptions; unreviewed drafts stay drafts** until a named reviewer approves them.
- Status recorded as `PASS` in `contracts/BE2_PROGRESS.md` and `contracts/BE2_ACCEPTANCE.md`.

## Files Changed

- `src/knowledge/catalog_api.py`: `KnowledgeGraph`, `CatalogAPI.graph/graph_nodes/graph_neighbors/graph_paths`; publication-manifest integrity checks.
- `src/knowledge/retrieval.py`: synonym expansion; only approved table descriptions enter retrieval context.
- `src/onboarding/pipeline.py`: description review decisions/statuses/history; approved-only indexing; synonyms persisted; publication crash coverage support.
- `src/onboarding/scale_report.py` (new): reproducible local scale sweep.
- `src/onboarding/__main__.py`: description review CLI flags.
- `tests/test_pipeline_trust.py`: graph query test and four-point crash matrix.
- `tests/test_scale_report.py` (new).
- `tests/test_synonym_recall.py` (new).
- `tests/test_description_review.py` (new).
- `contracts/BE2_SYNONYMS.json` (new): 7-term starter synonym set.
- `contracts/BE2_SCALE_REPORT.md` (new): generated scale report.
- `contracts/BE2_PROGRESS.md`, `contracts/BE2_ACCEPTANCE.md`: evidence/status updates.

## Key Decisions

- Graph queries are undirected; list-valued join endpoints expand pairwise; paths use bounded BFS.
- Crash failures are detected at catalog construction or index access depending on which artifact is ahead.
- Scale report is a single local run with environment recorded; cloud cost is explicitly unmeasured.
- Business aliases map to canonical schema terms before keyword ranking; synonyms are persisted in business-term docs.
- Descriptions default to `draft`; `review_descriptions` requires a named reviewer, stores approved text/history, and forces the description stage to rerun. Only approved text is indexed/served.

## Tests Actually Run

- `tests/test_pipeline_trust.py`: **8 passed** (after task 7).
- Task 2 targeted graph/join/query suites: **20 passed**.
- `tests/test_scale_report.py`: **1 passed**.
- Full suite after task 10: **82 passed, 1 skipped**.
- `tests/test_synonym_recall.py` + `tests/test_retrieval_eval.py` + `tests/test_pipeline_trust.py`: **14 passed**.
- Full suite after task 3: **83 passed, 1 skipped**.
- `tests/test_description_review.py`: **2 passed**.
- Full suite after task 1: **85 passed, 1 skipped**.
- `python -m src.onboarding review --help`: succeeded.

All pytest runs used `--basetemp="C:\Users\messi\AppData\Local\Temp\opencode\pytest-be2*"` because the default pytest temp/cache path is not writable.

## Remaining Limitations

- No graphical description-review UI; CLI/API workflow only, no model drafter.
- Synonym seed set is local/not business-approved; evaluation uses six curated synthetic cases.
- Scale timings are local observations, not SLA or cloud-cost measurements.
- Graph/query layer is local JSON only, no HTTP/graph service.
- Crash matrix covers publication windows, not every stage artifact.
- Learned embeddings, real UCI intake, OS-enforced isolation, and production API/deploy remain blocked by dependencies/privacy/infrastructure.

## Next Recommended Task

No requested tasks remain. If continuing the earlier backlog, start with confidence calibration, then metric resolver, planted-truth end-to-end scoring, fresh-build matrix, and independent generator edge-case scoring.

## Uncommitted Changes

Workspace has no `.git` metadata, so no commit/status operation was possible. All changes above are local working-tree edits; nothing was discarded or reset. The reference repo `Data_Scientist_Agent` was not modified.
