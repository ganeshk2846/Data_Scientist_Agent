# V2 evaluation

End-to-end evaluation of the integrated V2 agent on `major-project-update`,
produced by [`scripts/eval_v2.py`](../scripts/eval_v2.py). The section between the
`GENERATED` markers is rewritten by every run; the rest of this file is not.

## Read this first: what was verified, and on which data

| Claim | Verified on the **synthetic** V2 build (seeded fixture + synthetic layer) | Verified on the **real Olist** snapshot |
| --- | --- | --- |
| Routing, clarification, follow-ups, must-answer gate (107 questions, 24 scripts) | yes - every number below | **no** |
| Key numbers vs. reference SQL (11 cases) | yes - against the fixture's own rows | **no** |
| Planted effects E1-E5 recovered | yes - the plants exist only in synthetic tables | not applicable (plants are synthetic by design) |
| V1 `/api/ask` envelope shape and SSE event names | yes | **no** |
| Backend test suite | 1084 passed, 49 skipped | the 49 skipped tests are the ones that need the real snapshot |
| Same 107 questions and 24 scripts on a **real-scale stand-in** (the fixture generator at 32,951 products and 99,500 orders, scratch only) | 101/107 correct, 23/24 scripts, 9/9 must-answer | **no** - still generated data, only the volume is real |

**The real Olist snapshot (`brazil_ecommerce.sqlite`, 99,441 orders) is not in this
environment** - it is not committed (README section 5) and was not obtainable here.
Every result in this report was measured on `data/brazil_ecommerce_v2.sqlite` built
with `python scripts/build_v2.py --fixture`: a seeded, Olist-*shaped* stand-in with
4,975 orders whose figures describe nothing real, plus the ten synthetic tables and
the planted effects. No figure here is a statement about the real business, and none
of the real-snapshot metrics (99,441 orders, AOV, review score, freight) was checked.
To repeat the evaluation on the real data:

```bash
python scripts/build_v2.py --source brazil_ecommerce.sqlite
python scripts/eval_v2.py --serve --save-json docs/eval_v2/real.json --label "real Olist + synthetic"
```

Ollama was **not running** for any run, so every answer used the deterministic
fallbacks; this also confirms the V2 path works without the local model.

## Integration

All five track branches were already merged into `main` through pull requests #1-#5
(`v2-engines`, `claude/funny-fermat-irb7qc`, `claude/sharp-hawking-adb03f`,
`v2-p4-memory`, `claude/festive-noether-nspbh5`); none has a commit that `main` lacks.
`major-project-update` (`0baba20`) was a strict ancestor of `main`, so integration
was a fast-forward to `6e81f89`: every existing change on the branch is preserved,
no merge commit was needed and `main` was not modified.

| Check | Before integration (`0baba20`) | Integrated baseline (`6e81f89`) | Final |
| --- | --- | --- | --- |
| `pytest` (backend) | 494 passed, 47 skipped | 1058 passed, 49 skipped | 1084 passed, 49 skipped |
| `npm run typecheck` (frontend) | - | pass | pass |
| `npm run build` (frontend) | - | pass | pass |

## Method

- **Live backend, nothing mocked.** `--serve` starts uvicorn on the V2 build with a
  random bearer token; every question is a real `POST /api/v2/ask`, the finished
  `AnswerEnvelopeV2` is read from `GET /api/v2/runs/{id}`, and the SSE stream is
  replayed for each run. The only backend import is the frozen V1 contract, used to
  check the `/api/ask` envelope shape.
- **Expectations are independent of the code under test.** The 107-question bank
  ([`scripts/eval_v2_bank.yaml`](../scripts/eval_v2_bank.yaml)) and 24 multi-turn
  scripts ([`scripts/eval_v2_multiturn.yaml`](../scripts/eval_v2_multiturn.yaml)) are
  transcribed from `spec/v2/scope.md` sections 3-7, not from the Track 3 test bank;
  where the two disagree the spec wins (D10 and X10 expect a refusal). Key numbers
  are recomputed by reference SQL written from `semantics/metrics.md` on a read-only
  connection. Plants are scored against `data/SYNTHETIC_GROUND_TRUTH.md`, which the
  agent never reads.
- **One category per case**: `correct`, `routing_failure` (wrong outcome class or
  intent), `execution_failure` (HTTP error, timeout, status `error`/`blocked`),
  `insufficient_evidence` (routed correctly, no evidence-backed answer) or
  `incorrect_answer` (routed and answered, but a key number, check or plant failed).
- **What `correct` means.** 42 of the 107 cases carry a content assertion (11 key
  numbers by reference SQL, 11 planted effects, and spec checks such as the forecast
  anchor, an interval, the synthetic label, 2-3 ranked options, no causal wording).
  For the other 65, `correct` means the expected outcome class and intent with status
  `answered`/`clarify` - it does not grade the prose.
- **Planted effects** are only scored where the question's premise holds on the
  database under test (recomputed by reference SQL). The plants live in synthetic
  tables, so a real metric need not move with them: on the fixture, AOV rose in
  January 2018 (G4), review score rose in June 2018 (G5) and revenue rose in May
  2018 (G8). Those three are reported, not scored.
- **Latency** is the client wall clock from sending the POST to receiving the complete
  envelope, sequential, one request at a time, after one discarded warm-up, on this
  container; the server's `run_metrics.latency_ms` is shown beside it.
- **Before/after use one scorer.** The baseline was re-run with the final
  `eval_v2.py` against the pre-fix backend (`6e81f89`, served from a worktree with
  `--backend-root`). Every scorer change after the first baseline made scoring stricter
  or corrected the reference SQL (see the commit log); none relaxed an expectation.

```bash
python scripts/build_v2.py --fixture
python scripts/eval_v2.py --serve --save-json docs/eval_v2/final.json --baseline docs/eval_v2/baseline.json
```

Raw per-case results: [`docs/eval_v2/baseline.json`](eval_v2/baseline.json),
[`docs/eval_v2/final.json`](eval_v2/final.json).

<!-- BEGIN GENERATED: scripts/eval_v2.py -->

## Results - after fixes (incl. X6 scale fix and demo wording)

- Run at 2026-10-31 05:33 UTC on commit `afa3e04`; 22 s wall clock.
- Backend: live uvicorn, `POST /api/v2/ask` + `GET /api/v2/runs/{id}` (spawned by --serve).
- Database: `data/brazil_ecommerce_v2.sqlite` - 4,975 orders, sha256 `9eb8579c853953a7...`, snapshot `v2-20261030` - **seeded Olist-shaped FIXTURE + synthetic layer (not the real Olist data)**.
- Local model (Ollama): **unavailable** - every run used the deterministic fallbacks.
- Latency: client wall clock from sending the POST to receiving the complete envelope, sequential, one warm-up question discarded; columns are p50 / p95 / max in ms. Server latency is `run_metrics.latency_ms`.

### Before / after

| Measure | Baseline | This run |
| --- | --- | --- |
| Single-turn cases correct | 89/107 (83%) | 102/107 (95%) |
| Multi-turn scripts passed | 19/24 (79%) | 23/24 (96%) |
| Multi-turn turns correct | 46/51 (90%) | 50/51 (98%) |
| Must-answer returned `answered` | 9/9 (100%) | 9/9 (100%) |
| V1 regression questions with the V1 shape | 3/3 (100%) | 3/3 (100%) |
| routing_failure (single-turn) | 2 | 2 |
| execution_failure (single-turn) | 0 | 0 |
| insufficient_evidence (single-turn) | 7 | 3 |
| incorrect_answer (single-turn) | 9 | 0 |

### Summary

| Measure | Result |
| --- | --- |
| Single-turn cases correct | 102/107 (95%) |
| Multi-turn scripts fully correct | 23/24 (96%) |
| Multi-turn turns correct | 50/51 (98%) |
| Must-answer (scope.md 7) returned `answered` | 9/9 (100%) |
| V1 `/api/ask` regression (V1 envelope shape + V1 SSE names) | 3/3 (100%) |

### Per intent (single-turn)

Denominators are cases in the section. *Routed* = expected outcome class and intent. *Answered* = status `answered`. *Chart* is over answered cases. *Clarified* = status `clarify` (expected for the clarify and vague sections).

| Section | Cases | Correct | Routed | Answered | Chart (of answered) | Clarified | Latency p50/p95/max ms | Server p50 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| discovery | 10 | 9/10 (90%) | 9/10 (90%) | 9/10 (90%) | 0/9 (0%) | 1/10 (10%) | 12 / 48 / 48 | 5 |
| clarify | 10 | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 0/0 (-) | 10/10 (100%) | 11 / 17 / 17 | 3 |
| descriptive | 10 | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 9/10 (90%) | 0/10 (0%) | 27 / 33 / 33 | 21 |
| diagnostic | 14 | 14/14 (100%) | 14/14 (100%) | 14/14 (100%) | 14/14 (100%) | 0/14 (0%) | 371 / 518 / 1320 | 362 |
| impact | 10 | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 25 / 27 / 27 | 16 |
| forecast | 10 | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 15 / 757 / 757 | 9 |
| scenario | 10 | 6/10 (60%) | 9/10 (90%) | 6/10 (60%) | 6/6 (100%) | 1/10 (10%) | 26 / 542 / 542 | 20 |
| prescriptive | 10 | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 264 / 1095 / 1095 | 256 |
| compound | 10 | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 281 / 710 / 710 | 265 |
| vague | 10 | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 0/0 (-) | 10/10 (100%) | 9 / 10 / 10 | 2 |
| v1_regression | 3 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 0/3 (0%) | 34 / 38 / 38 | 27 |
| **all** | 107 | 102/107 (95%) | 105/107 (98%) | 82/107 (77%) | 72/82 (88%) | 22/107 (21%) | 27 / 542 / 1320 | |

### Failure taxonomy (single-turn)

| Section | correct | routing_failure | execution_failure | insufficient_evidence | incorrect_answer |
| --- | --- | --- | --- | --- | --- |
| discovery | 9 | 1 | 0 | 0 | 0 |
| clarify | 10 | 0 | 0 | 0 | 0 |
| descriptive | 10 | 0 | 0 | 0 | 0 |
| diagnostic | 14 | 0 | 0 | 0 | 0 |
| impact | 10 | 0 | 0 | 0 | 0 |
| forecast | 10 | 0 | 0 | 0 | 0 |
| scenario | 6 | 1 | 0 | 3 | 0 |
| prescriptive | 10 | 0 | 0 | 0 | 0 |
| compound | 10 | 0 | 0 | 0 | 0 |
| vague | 10 | 0 | 0 | 0 | 0 |
| v1_regression | 3 | 0 | 0 | 0 | 0 |
| **all** | 102 | 2 | 0 | 3 | 0 |

### Must-answer gate (V2-ANS-2)

| Ref | Question | Status | Category |
| --- | --- | --- | --- |
| D1 | What data do you have? | answered | correct |
| S5 | What are the spikes across all months? | answered | correct |
| G1 | Why did revenue drop in the top category in April 2018? | answered | correct |
| I1 | How much did the April 2018 drop cost us? | answered | correct |
| F1 | Forecast revenue for the next 3 months | answered | correct |
| X6 | What if we raise prices 5%? | answered | correct |
| P1 | Which customer segment should we target? | answered | correct |
| K1 | How does revenue trend look today and what will it be in 3 months? | answered | correct |
| U1 turn 2 | What about SP? (follow-up) | answered | correct |

### Planted effects (data/SYNTHETIC_GROUND_TRUTH.md)

A diagnostic answer *recovers* a plant when its conclusion or a claim names the planted cause; it *misattributes* when a co-movement claim names the planted confounder instead. Every row reads synthetic tables, so these are results on generated data only.

*Premise* is the change the question asserts, recomputed by reference SQL (current window minus the previous period); where it is false on this database the plant cannot be recovered and is not scored.

| Ref | Plant | Question | Status | Premise (measured change) | Recovered | Confounder as driver | Cause tokens found |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G1 | E1 | Why did revenue drop in the top category in April 2018? | answered | holds (-504.5) | yes | no | paid_search |
| G3 | E2 | Why did order count fall in December 2017? | answered | holds (-93) | yes | no | stockout |
| G4 | E3 | Why did AOV fall in January 2018? | answered | FALSE (+1.39) | n/a (cause named: no) | no | - |
| G5 | E4 | Why did review scores drop in June 2018? | answered | FALSE (+0.1477) | n/a (cause named: no) | no | - |
| G8 | E1 | Which states drove the revenue decline in May 2018? | answered | FALSE (+4,173) | n/a (cause named: no) | no | - |
| G10 | E4 | Did the carrier cause the delivery delays? | answered | - | yes | no | jadlog, sla_breach |
| E-G1s | E1 | Why did web sessions drop in April 2018? | answered | holds (-1.145e+05) | yes | no | paid_search |
| E-G3s | E2 | Why did the stockout rate spike in December 2017? | answered | holds (+0.009016) | yes | no | cama_mesa_banho, beleza_saude, esporte_lazer |
| E-G4s | E3 | Why did conversion rate rise in January 2018? | answered | holds (+0.003281) | yes | no | discount |
| E-G5s | E4 | Why did the return rate rise in June 2018? | answered | holds (+0.01436) | yes | no | sla_breach |
| X6 | E5 | What if we raise prices 5%? | answered | - | yes | no | elasticity -1.61 (-2.25 to -0.97) vs planted -1.5 |

Plants scored: 8/8 recovered where the premise holds; 3 not scored (premise false); 0 answers named a confounder as the driver.


### Multi-turn scripts

| Script | Spec | Turns correct | Result | Failing turn: reason |
| --- | --- | --- | --- | --- |
| U1 | 6.2 U1 / must-answer 4 | 2/2 | pass | - |
| U2 | 6.2 U2 - 'why' after a single total must clarify | 2/2 | pass | - |
| U3 | 6.2 U3 | 2/2 | pass | - |
| U4 | 6.2 U4 - forecast of 27 series clarifies down or forecasts the aggregate | 2/2 | pass | - |
| U5 | 6.2 U5 | 2/2 | pass | - |
| U6 | 6.2 U6 | 2/2 | pass | - |
| U7 | 6.2 U7 | 2/2 | pass | - |
| U8 | 6.2 U8 | 2/2 | pass | - |
| U9 | 6.2 U9 | 2/2 | pass | - |
| U10 | 6.2 U10 - the third turn inherits from the second; the fourth escalates and keeps RJ | 4/4 | pass | - |
| M-window | 6.1 window shift | 1/2 | FAIL | 2 `And last year?`: incorrect_answer - period 2017-01..2017-08 != 2017-01..2017-12 |
| M-why | 6.1 intent escalation 'Why?' after a change | 2/2 | pass | - |
| M-drill | 6.1 drill-down | 2/2 | pass | - |
| M-grain | 6.1 grain change | 2/2 | pass | - |
| M-metric | 6.1 metric swap | 2/2 | pass | - |
| M-ref | 6.1 reference | 2/2 | pass | - |
| M-forecast-filter | 6.1 intent escalation 'Forecast that' with an inherited filter | 2/2 | pass | - |
| M-why-impact | 6.1 escalation chain: why -> so what | 2/2 | pass | - |
| CL-option | 3.2 C1 - choosing an offered option answers the original question | 2/2 | pass | - |
| CL-default | 3.2 - accepting the stated default answers the question | 2/2 | pass | - |
| CL-text | 3.2 C3 - a free-text reply resolves the asked slot | 2/2 | pass | - |
| CL-then-follow | 3.2 + 6.1 - a clarified answer is context for the next follow-up | 3/3 | pass | - |
| RESET | 6.3 rule 1 - after a new topic there is no context to inherit | 3/3 | pass | - |
| COLD | 6.3 rule 1 / C6 - a follow-up with no prior turn clarifies | 1/1 | pass | - |

Turn categories: correct 50, routing_failure 0, execution_failure 0, insufficient_evidence 0, incorrect_answer 1; turn latency p50/p95/max 29 / 504 / 818 ms.

### V1 regression (`POST /api/ask`)

| Question | Status | SSE events | V1 envelope keys | Latency ms |
| --- | --- | --- | --- | --- |
| How many orders were there in August 2018? | answered | answer, step_finished, step_started | match | 26 |
| How did revenue in 2018 compare to 2017? | answered | answer, step_finished, step_started | match | 35 |
| Was order count unusual in August 2018? | answered | answer, step_finished, step_started | match | 23 |

### Every single-turn case

| Ref | Expected | Got | Category | Latency ms | Reason |
| --- | --- | --- | --- | --- | --- |
| D1 | answer/discovery | answered/discovery | correct | 48 | - |
| D2 | answer/discovery | answered/discovery | correct | 14 | - |
| D3 | answer/discovery | answered/discovery | correct | 36 | - |
| D4 | answer/discovery | answered/discovery | correct | 11 | - |
| D5 | answer/discovery | answered/discovery | correct | 9 | - |
| D6 | answer/discovery | answered/discovery | correct | 9 | - |
| D7 | answer/discovery | answered/discovery | correct | 9 | - |
| D8 | answer/discovery | answered/discovery | correct | 36 | - |
| D9 | answer/discovery | answered/discovery | correct | 37 | - |
| D10 | refuse/discovery | clarify/clarify | routing_failure | 9 | expected refuse, got clarify (asked: "I don't hold customer age, customer gender. Would one of these help instead?") |
| C1 | clarify/clarify | clarify/clarify | correct | 17 | - |
| C2 | clarify/clarify | clarify/clarify | correct | 10 | - |
| C3 | clarify/clarify | clarify/clarify | correct | 8 | - |
| C4 | clarify/clarify | clarify/clarify | correct | 9 | - |
| C5 | clarify/clarify | clarify/clarify | correct | 9 | - |
| C6 | clarify/clarify | clarify/clarify | correct | 12 | - |
| C7 | clarify/clarify | clarify/clarify | correct | 12 | - |
| C8 | clarify/clarify | clarify/clarify | correct | 12 | - |
| C9 | clarify/clarify | clarify/clarify | correct | 10 | - |
| C10 | clarify/clarify | clarify/clarify | correct | 13 | - |
| S1 | answer/descriptive | answered/descriptive | correct | 29 | - |
| S2 | answer/descriptive | answered/descriptive | correct | 32 | - |
| S3 | answer/descriptive | answered/descriptive | correct | 33 | - |
| S4 | answer/descriptive | answered/descriptive | correct | 27 | - |
| S5 | answer/descriptive | answered/descriptive | correct | 24 | - |
| S6 | answer/descriptive | answered/descriptive | correct | 24 | - |
| S7 | answer/descriptive | answered/descriptive | correct | 25 | - |
| S8 | answer/descriptive | answered/descriptive | correct | 32 | - |
| S9 | answer/descriptive | answered/descriptive | correct | 28 | - |
| S10 | answer/descriptive | answered/descriptive | correct | 27 | - |
| G1 | answer/diagnostic | answered/diagnostic | correct | 321 | - |
| G2 | answer/diagnostic | answered/diagnostic | correct | 278 | - |
| G3 | answer/diagnostic | answered/diagnostic | correct | 469 | - |
| G4 | answer/diagnostic | answered/diagnostic | correct | 456 | premise false on this database (measured change +1.39); E3 not scored |
| G5 | answer/diagnostic | answered/diagnostic | correct | 227 | premise false on this database (measured change +0.1477); E4 not scored |
| G6 | answer/diagnostic | answered/diagnostic | correct | 518 | - |
| G7 | answer/diagnostic | answered/diagnostic | correct | 290 | - |
| G8 | answer/diagnostic | answered/diagnostic | correct | 339 | premise false on this database (measured change +4,173); E1 not scored |
| G9 | answer/diagnostic | answered/diagnostic | correct | 482 | - |
| G10 | answer/diagnostic | answered/diagnostic | correct | 1320 | - |
| E-G1s | answer/diagnostic | answered/diagnostic | correct | 275 | - |
| E-G3s | answer/diagnostic | answered/diagnostic | correct | 403 | - |
| E-G4s | answer/diagnostic | answered/diagnostic | correct | 410 | - |
| E-G5s | answer/diagnostic | answered/diagnostic | correct | 244 | - |
| I1 | answer/impact | answered/impact | correct | 25 | - |
| I2 | answer/impact | answered/impact | correct | 25 | - |
| I3 | answer/impact | answered/impact | correct | 27 | - |
| I4 | answer/impact | answered/impact | correct | 26 | - |
| I5 | answer/impact | answered/impact | correct | 23 | - |
| I6 | answer/impact | answered/impact | correct | 25 | - |
| I7 | answer/impact | answered/impact | correct | 25 | - |
| I8 | answer/impact | answered/impact | correct | 23 | - |
| I9 | answer/impact | answered/impact | correct | 20 | - |
| I10 | answer/impact | answered/impact | correct | 23 | - |
| F1 | answer/forecast | answered/forecast | correct | 16 | - |
| F2 | answer/forecast | answered/forecast | correct | 14 | - |
| F3 | answer/forecast | answered/forecast | correct | 21 | - |
| F4 | answer/forecast | answered/forecast | correct | 15 | - |
| F5 | answer/forecast | answered/forecast | correct | 757 | - |
| F6 | answer/forecast | answered/forecast | correct | 15 | - |
| F7 | answer/forecast | answered/forecast | correct | 13 | - |
| F8 | answer/forecast | answered/forecast | correct | 13 | - |
| F9 | answer/forecast | answered/forecast | correct | 537 | - |
| F10 | answer/forecast | answered/forecast | correct | 528 | - |
| X1 | answer/scenario | answered/scenario | correct | 29 | - |
| X2 | answer/scenario | answered/scenario | correct | 40 | - |
| X3 | answer/scenario | answered/scenario | correct | 57 | - |
| X4 | answer/scenario | insufficient_evidence/scenario | insufficient_evidence | 24 | Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'grew to 85%' has no fitted relationship to perturb, so no figure is invented. |
| X5 | answer/scenario | answered/scenario | correct | 27 | - |
| X6 | answer/scenario | answered/scenario | correct | 542 | - |
| X7 | answer/scenario | insufficient_evidence/scenario | insufficient_evidence | 23 | Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'restored the marketing spend we cut' has no fitted relationship to perturb, so no figur |
| X8 | answer/scenario | answered/scenario | correct | 24 | - |
| X9 | answer/scenario | insufficient_evidence/scenario | insufficient_evidence | 26 | Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'eliminated the stockouts' has no fitted relationship to perturb, so no figure is invent |
| X10 | refuse/scenario | clarify/clarify | routing_failure | 8 | expected refuse, got clarify (asked: "I don't hold an Argentinian market. Would one of these help instead?") |
| P1 | answer/prescriptive | answered/prescriptive | correct | 340 | - |
| P2 | answer/prescriptive | answered/prescriptive | correct | 287 | - |
| P3 | answer/prescriptive | answered/prescriptive | correct | 248 | - |
| P4 | answer/prescriptive | answered/prescriptive | correct | 295 | - |
| P5 | answer/prescriptive | answered/prescriptive | correct | 279 | - |
| P6 | answer/prescriptive | answered/prescriptive | correct | 1095 | - |
| P7 | answer/prescriptive | answered/prescriptive | correct | 44 | - |
| P8 | answer/prescriptive | answered/prescriptive | correct | 245 | - |
| P9 | answer/prescriptive | answered/prescriptive | correct | 249 | - |
| P10 | answer/prescriptive | answered/prescriptive | correct | 22 | - |
| K1 | answer/descriptive | answered/descriptive,forecast | correct | 710 | - |
| K2 | answer/diagnostic | answered/diagnostic | correct | 296 | - |
| K3 | answer/diagnostic | answered/diagnostic,impact,prescriptive | correct | 298 | - |
| K4 | answer/descriptive | answered/descriptive,scenario | correct | 51 | - |
| K5 | answer/descriptive | answered/descriptive,forecast | correct | 581 | - |
| K6 | answer/diagnostic | answered/diagnostic,impact | correct | 245 | - |
| K7 | answer/descriptive | answered/descriptive,prescriptive | correct | 35 | - |
| K8 | answer/discovery | answered/discovery,diagnostic | correct | 479 | - |
| K9 | answer/forecast | answered/forecast,scenario | correct | 33 | - |
| K10 | answer/diagnostic | answered/diagnostic,impact,prescriptive | correct | 267 | - |
| V1 | clarify/clarify | clarify/clarify | correct | 10 | - |
| V2 | clarify/clarify | clarify/clarify | correct | 9 | - |
| V3 | clarify/clarify | clarify/clarify | correct | 10 | - |
| V4 | clarify/clarify | clarify/clarify | correct | 8 | - |
| V5 | clarify/clarify | clarify/clarify | correct | 8 | - |
| V6 | clarify/clarify | clarify/clarify | correct | 9 | - |
| V7 | clarify/clarify | clarify/clarify | correct | 10 | - |
| V8 | clarify/clarify | clarify/clarify | correct | 9 | - |
| V9 | clarify/clarify | clarify/clarify | correct | 9 | - |
| V10 | clarify/clarify | clarify/clarify | correct | 9 | - |
| R-1 | answer/descriptive | answered/descriptive | correct | 30 | - |
| R-2 | answer/descriptive | answered/descriptive | correct | 38 | - |
| R-3 | answer/descriptive | answered/descriptive | correct | 34 | - |

<!-- END GENERATED: scripts/eval_v2.py -->

## Fixes, in order of demo impact

| Area | Failure in the baseline | Fix | Cases fixed |
| --- | --- | --- | --- |
| WHY | The live diagnostic only correlated monthly levels over the whole history, so no planted cause was named; the promotion indicator its own purpose string promised was never read, so the E3 confounder (boleto) was blamed; the outcome was tested against itself ("sessions co-moves with sessions"). | Window screen in `engines/diagnostic.py` (lagged level vs. trailing median, robust z, BH across candidates and lags, grade 1, timing evidence only); `promo_discount` indicator; expected-sign priors per outcome class; outcome excluded from its own candidates. | G1, G3, E-G1s, E-G4s, E-G5s |
| Forecast | A 3-month forecast read as one month with no anchor; a horizon the history cannot support was cut silently. | Answer names the anchor (2018-08), the months covered, every monthly point, and any bounded horizon (F9). | F1-F10 wording (were already routed) |
| Follow-ups | "What did it add?" after the Nov-2017 spike was skipped (no 12-month history for an expected value); "Why is that number so low?" clarified; "what if freight rises 10%?" after a forecast had no fit. | Impact falls back to the previous window with the reason stated; a judgement ("so low") is answered against the year before (a bare "Why?" still clarifies, U2); measured multiplier what-ifs (below). | U8, M-ref, U9 |
| Clarification | Accepting the default for "How are sales doing?" asked a second question about the window, though that ambiguity predated the reply. | Round 2 is kept only for a slot the chosen option touched; otherwise the stated default applies and is recorded. | CL-default |
| What | "What was revenue in 2017?" never stated the total; a single month read "moved from 326 to 326, 0%". | One more governed query over the whole window (so distinct counts and ratios are measured, not summed). | S2, S8, R-3 |
| Now what | The must-answer "Which customer segment should we target?" returned no options. | 2-3 ranked options from the engine's clusters, with assumptions, trade-offs, monitoring and what would change the ranking. | P1 |
| What if | Every non-price what-if was `insufficient_evidence`. | A stated multiplier on a governed metric is applied to measured totals of the last 3 complete months and sized by the impact engine, labelled a mechanical what-if. | X1, X3, X5, X8 |

### Second round: X6 at real scale, and the demo answers read in full

| Area | Failure | Fix | Cases |
| --- | --- | --- | --- |
| What if (must-answer X6) | "What if we raise prices 5%?" returned `insufficient_evidence` at the real catalogue size: `prep.daily_list_price` looped over 32,951 products (~80 s), the plan's 60 s budget skipped the baseline step and the scenario with it. The fixture's 260 products hid it. | Vectorised list-price panel (81 s -> 0.35 s, identical output within 3e-14); X6 now answers in ~1.5 s at that scale, elasticity -1.64 (interval -1.83 to -1.45; planted -1.5). | X6 at scale |
| What if, no synthetic tables | With `DS_AGENT_DB` unset there is no price history; the refusal said "only price-change scenarios have a fitted response" in reply to a price change. | Still no figure; the reason names the missing tables and how to build them. | - |
| Compound K1 | The trend total introduced in round one used the forecast's extended fit history: "Revenue for 2017-09 to 2018-08 was R$ 615,120.84" where the window alone is R$ 471,889.80. | The total uses the asked window (`summary_period`). | K1 wording |
| Wording | "Revenue for total was ... against the comparison window"; "Gmv"/"Aov"; "no candidate co-moved" next to a named candidate. | Both windows named; acronyms kept; the sentence says which test found nothing. | S4, G-cases |

The status-only grade did not catch the K1 total or the wording; reading every demo
answer did. The demo itself is in [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md), replayed by
`scripts/verify_demo.py` (18/18 steps on the fixture build and on the real-scale
stand-in).

Each fix has regression tests in `backend/tests/test_window_screen.py`,
`backend/tests/test_v2_answer_fixes.py` and `backend/tests/test_price_panel_scale.py`
(26 new tests, on the real pipeline over the seeded build). No existing test,
assertion or skip marker was changed.

## Still not working

| Ref | Category | Why it is not fixed |
| --- | --- | --- |
| D10, X10 | routing_failure | The spec (scope.md 3.1, 3.7) says *refusal*; the agent returns `clarify` that names the missing attribute and offers alternatives. The existing Track 3 test bank (`backend/tests/data/question_bank_v2.yaml`) pins `clarify` for both, so changing the status would mean editing an existing test. Needs a decision on which document is right. |
| X4, X7, X9 | insufficient_evidence | "credit-card share to 85%", "restore the spend we cut" and "eliminate the stockouts" are absolute or additive targets with no measured multiplier; X7 needs a fitted spend-to-orders response and X9 a forgone-demand model. The agent declines rather than inventing a coefficient. |
| M-window | incorrect_answer | "And last year?" after "GMV in 2018" resolves to Jan-Aug 2017 (aligned to 2018's complete months) instead of all of 2017. Defensible as a like-for-like window, but it is not what the expectation (a plain window shift, 6.1) says, and the answer does not state the alignment. |
| G4, G5, G8 | not scored | On the fixture the asserted drop did not happen. Whether E3/E4/E1 are recoverable through these real metrics can only be checked on the real snapshot. |
| Discovery | - | Discovery answers carry no chart (0/9 answered); scope.md does not require one. |
| I9 (real-scale stand-in only) | insufficient_evidence | "What are the stockouts costing us?" finds a zero baseline at that volume. |
| I2 | graded correct, answers poorly | "What is SP worth to us?" answers with a change against a baseline rather than SP's share - the routing-only grade does not see it. |
| Browser gates | not run | `npm run verify:features`, `verify:live` and a click-through of the hero chips could not run: the project's Playwright 1.64.1 expects Chromium revision 1248 and this environment has 1243. The demo was verified over the API the UI uses; typecheck and build are clean. |

Known limits of this evaluation: 65 cases are graded on routing and status only; the
plant tokens are a text match on the conclusion and claims; the elasticity check uses
the interval the answer reports; latency was measured on one container with no
competing load and no local model.

## Contracts and dependencies

- No frozen contract was changed. The window screen is reported through the engine's
  own `ranked_drivers` table, because `DiagnosticEvidence.method` in
  `backend/src/contracts/v2.py` is a closed `Literal` without a window-change method.
  If the screen should appear in `DiagnosticResult.indicator_drivers`, the contract
  needs a new method value - proposed, not made.
- No dependency was added to the project. `ruff` was installed locally only to lint
  the changed files.
