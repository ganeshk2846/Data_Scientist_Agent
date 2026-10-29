# AN-1 Phase 3 Design: Ground Truth Contract and Analyst Scoring Foundation

**Status:** Implementation complete, awaiting review. No commit or push was performed.

**Requirement IDs addressed:** ANA-5, ANOM-9, DRV-10, DATA-4, DATA-9 (contract shape only).

## 1. Ownership

| Area | Owner | Phase 3 boundary |
| --- | --- | --- |
| Synthetic warehouse generator and planted-truth hook | BE-2 | BE-2 writes the warehouse, injects plants through its plugin hook, and emits the manifest. AN-1 does not create generator code. |
| Ground-truth records and analyst scoring | AN-1 | AN-1 owns the shared manifest contract and pure scoring functions. AN-1 does not read held-out files, run benchmarks, persist results, or set a release gate. |
| Evaluation runner, benchmarking, result persistence, release gate | BE-1 | BE-1 calls AN-1 scoring functions and owns `eval/`, baselines, reports, and pass/fail enforcement. |
| Locked held-out split | Lead / BE-2 | The Lead controls access. BE-2 stores the held-out manifest outside the agent-readable path. Only scoring code receives records. |

Risk Analyst and Advisor remain deferred until v0.5.

## 2. Shared contract

`GroundTruthManifest` and its nested records live in
`backend/src/contracts/models.py` and inherit the existing frozen
`ContractModel` base (`extra="forbid"`). No runtime path loads the manifest.

### 2.1 Field provenance

Labels: **DOC** = required by `spec/Interfaces.md`, `docs/DESIGN_DETAIL.md`,
or `docs/Product.md`; **CODE** = derived from existing code conventions;
**PROPOSED** = added for this phase and requiring future approval.

| Model | Field | Status | Notes |
| --- | --- | --- | --- |
| `GroundTruthManifest` | `snapshot_id` | DOC | Interfaces 7.1; validated as an identifier. |
| | `seed` | DOC | Interfaces 7.1; non-negative deterministic seed. |
| | `generator_version` | DOC | Interfaces 7.1 provenance. |
| | `split` | DOC | Interfaces 7.1 and design C4; `build` versus `heldout`. |
| | `anomalies` | DOC | Interfaces 7.1; default empty tuple. |
| | `drivers` | DOC | Interfaces 7.1; references must resolve to an anomaly. |
| | `confounders` | DOC | Interfaces 7.1; references must resolve to an anomaly. |
| | `negative_controls` | DOC | Interfaces 7.1. |
| | `churn_process` | DOC | Interfaces 7.1 / design C3; optional single record. |
| | `insufficient_evidence_cases` | PROPOSED | Not in Interfaces 7.1; required by the Phase 3 task. Smallest compatible addition. |
| | `is_heldout` | CODE | Read-only property; does not load or expose held-out data. |
| `PlantedAnomaly` | `anomaly_id`, `metric`, `unit`, `kind`, `start`, `end`, `magnitude_pct` | DOC | Interfaces 7.1. Identifiers are validated; `end` may be omitted; `end` cannot precede `start`. |
| `PlantedDriver` | `anomaly_id`, `cause_kind`, `cause`, `true_share` | DOC | Interfaces 7.1. Finite share; no range imposed because documentation does not define one. |
| `Confounder` | `anomaly_id`, `moves_with`, `is_cause` | DOC | Interfaces 7.1. `is_cause` is fixed to `False`. |
| `NegativeControl` | `control_id`, `metric`, `unit`, `period`, `kind` | DOC | Interfaces 7.1; reuses the existing `Period` contract. |
| `ChurnProcessMetadata` | `process_id`, `description`, `params`, `true_risk_segments`, `label_table` | DOC | Interfaces 7.1. Future risk use only. Parameter values are finite; keys are identifiers; serialization order is deterministic. |
| `TrueRiskSegment` | `segment`, `relative_risk` | DOC | Interfaces 7.1; `relative_risk` is finite. |
| `InsufficientEvidenceCase` | `case_id`, `metric`, `unit`, `period`, `reason` | PROPOSED | Phase 3 task. `reason` is a documented expectation, not a runtime instruction. |
| `TruthUnit` | `dimension`, `value` | CODE | Extracted because Interfaces repeats the same unit shape in anomalies, drivers, confounders and controls. |

### 2.2 Deliberate omissions and ambiguity

- **`sql_traps` is not included.** Interfaces 7.1 lists seeded SQL traps, but
  the Phase 3 task limits truth kinds to anomalies, drivers, confounders,
  negative controls, churn metadata and insufficient-evidence cases. Interfaces
  also requires `correct_result_sql`, which is executable text. Adding it would
  conflict with the requirement that truth records contain no executable
  instructions. SQL traps remain BE-2-owned work for a later contract review.
- **`churn_process` is singular.** Interfaces 7.1 defines a single object. If
  BE-2 needs multiple processes, that is a future breaking change requiring
  shared-contract review.
- **`end` semantics are not specified by the documentation.** This phase treats
  `start` as inclusive and requires any provided `end` not to precede `start`.
  Scoring uses the presence of `end` only to decide whether detection delay is
  computable.
- **`insufficient_evidence_cases` has no documented shape.** The smallest shape
  that records an evaluation identity, scope and expected insufficiency reason
  is proposed.
- **No field carries an import path, file path, module name, callable, SQL,
  shell command or code.** Unknown fields are rejected, so a manifest cannot
  introduce one through an extension.
- **No secrets or customer-level raw data are modeled.** `TruthUnit.value` is a
  business label such as a region or category, not an email, credential, token
  or per-customer record. The manifest holds aggregate truth only.

## 3. Leakage prevention

- The contract and scoring module never read a file. Callers inject typed
  `PlantedAnomaly`, `PlantedDriver`, `NegativeControl` and summary records.
- `backend/src/analysts/scoring.py` imports only `math`, `datetime`, `typing`,
  `pydantic` and local `contracts.models`.
- There is no database, network, model client, subprocess, `eval`, `exec`, or
  dynamic-import use in scoring.
- `split="heldout"` is represented but is not a key or switch for loading data.
  Access remains the Lead/BE-2 responsibility.
- Runtime analyst code does not import the scoring module, the manifest, or the
  held-out path. No orchestrator, service, router or analyst wiring was changed.

## 4. Scoring module

`backend/src/analysts/scoring.py` exposes pure, deterministic functions.

### Anomaly scoring

- `score_anomaly_detection(output, truth, detection_delay_tolerance_days=...)`
  reports `true_positive` or `false_negative`.
- `score_false_alert(output, truth)` reports `false_alert` or `true_negative`
  for negative controls.
- `summarize_anomaly_scores(scores, detection_delay_tolerance_days=...)`
  reports counts, detection rate, false-alert rate and delay statistics.
- Detection delay is emitted only when the truth record has both `start` and
  `end`, and only for a detected anomaly.
- An empty or wholly unscored input fails closed with
  `status="insufficient_evidence"`.

### Driver scoring

- `score_driver_attribution(output, anomaly, drivers, share_tolerance=...,
  reconciliation_tolerance=...)` reports top-1 hit, top-3 hit, matched rank,
  contribution agreement against `true_share`, and reconciliation validity.
- `summarize_driver_scores(scores, ...)` reports hit counts and rates.
- Truth-driver `anomaly_id` values must match the supplied anomaly; a mismatch
  fails closed as `invalid_input`.
- Empty or unscored input fails closed with `insufficient_evidence`.

### Result models

The existing contracts contain analyst result models (`AnomalyResult`,
`DriverResult`) but no scoring result models. This phase therefore adds local
scoring-only models in `scoring.py`:

- `AnomalyCaseScore`
- `AnomalyScoringSummary`
- `DriverCaseScore`
- `DriverScoringSummary`

They are not added to the shared pipeline contracts and are not consumed by the
orchestrator or API. **Shared-contract review is required before BE-1 persists
or serves these records.** This is reported as a limitation rather than a silent
scope expansion.

Every field on these four scoring models is **PROPOSED** for future approval;
they are local evaluation records derived from the documented ANOM-9 and DRV-10
metrics (detection, false alerts, delay, top-1/top-3, contribution agreement and
reconciliation).

## 5. Test strategy

Testing is fixture-only and in memory:

- `backend/tests/test_an1_ground_truth_contract.py` covers valid parsing,
  every supported truth kind, malformed manifests, unknown fields, invalid
  dates and identifiers, non-finite numbers, deterministic serialization and
  the absence of executable/runtime fields.
- `backend/tests/test_an1_scoring.py` covers anomaly hit/miss, false alerts,
  supported and unsupported detection delay, driver top-1/top-3/miss,
  contribution agreement, reconciliation validity, empty input, mismatched IDs,
  insufficient-evidence input, repeat determinism and finite outputs.

No SQLite database, held-out file, network call or model was used.

Validation command, run from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m pytest -q tests\test_an1_ground_truth_contract.py tests\test_an1_scoring.py tests\test_an1_registry.py tests\test_an1_architecture.py tests\test_analyst_harness.py
```

Result: `128 passed`.

## 6. Scoring limitations

- These functions score synthetic fixtures. They do not measure production
  performance and must not be presented as production accuracy.
- Detection correctness depends on the analyst's `verdict` and evaluated
  window. Detection delay is a window-start offset against truth `start`; it is
  not a real-time alerting delay.
- Contribution agreement compares a matched driver's `share` with the planted
  `true_share` within an explicit tolerance. It does not prove causality.
- Reconciliation validity is a numeric tolerance check on the analyst's
  reported reconciliation error.
- The module does not implement benchmark runners, result persistence, the
  release gate, held-out loading, model-based scoring or any Risk/Advisor
  scoring.
- `sql_traps` and any executable truth payload are out of scope for this
  contract version.

## 7. Deferred Risk and Advisor work

Risk Analyst and Advisor remain planned and unimplemented until v0.5. The churn
process metadata is contract-only for future use. No churn label, model,
calibration, segmentation, Action Library, recommendation ranking or advisor
output exists in this phase.

## 8. Requirement IDs

| ID | Phase 3 contribution | Not claimed |
| --- | --- | --- |
| ANA-5 | Pure scoring functions against typed planted truth. | No complete evaluation of every analyst; Risk/Advisor absent. |
| ANOM-9 | Recall, false-alert count/rate and conditional detection delay scoring. | No comparison against the ±2σ baseline runner. |
| DRV-10 | Top-1, top-3, contribution agreement and reconciliation scoring. | No comparison against the largest-absolute-change baseline runner. |
| DATA-4 | Shared manifest shape for generator-written truth. | The generator and planted truth do not yet exist in this repository. |
| DATA-9 | Held-out split identity and no runtime access in scoring. | BE-2/Lead storage and access controls remain outside AN-1. |

EVAL-1 through EVAL-8 remain BE-1's runner, reporting and release-gate work.
This phase does not claim any EVAL result or measured accuracy.

## 9. Shared-contract review requirement

The `GroundTruthManifest` additions and local scoring result models require
review by the Lead and BE-2 before BE-2 depends on the shape or BE-1 persists
scores. Any further field addition must go through the project shared-contract
process and be documented here first.

## 10. Explicit non-goals

Phase 3 does not:

- create a synthetic warehouse, planted data or a held-out snapshot;
- read or expose held-out data to runtime analyst code;
- run any evaluation, benchmark or release gate;
- measure or claim analyst accuracy;
- implement Risk Analyst, Advisor or the Action Library;
- change anomaly, driver, harness, registry, orchestrator, service, evidence,
  SQL, gateway, router, frontend, database or dependency files;
- modify existing tests or the timing test;
- add packages or dependencies.

## 11. Files changed

Added:

- `backend/src/analysts/scoring.py`
- `backend/tests/test_an1_ground_truth_contract.py`
- `backend/tests/test_an1_scoring.py`
- `docs/an1/PHASE3_DESIGN.md`

Modified:

- `backend/src/contracts/models.py` (shared-contract work explicitly approved
  for this phase)

Nothing was staged, committed or pushed.
