# V2 evaluation

<!-- BEGIN GENERATED: scripts/eval_v2.py -->

## Results - baseline (integrated, before fixes)

- Run at 2026-10-31 03:42 UTC on commit `6e81f89`; 20 s wall clock.
- Backend: live uvicorn, `POST /api/v2/ask` + `GET /api/v2/runs/{id}` (spawned by --serve).
- Database: `data/brazil_ecommerce_v2.sqlite` - 4,975 orders, sha256 `9eb8579c853953a7...`, snapshot `v2-20261030` - **seeded Olist-shaped FIXTURE + synthetic layer (not the real Olist data)**.
- Local model (Ollama): **unavailable** - every run used the deterministic fallbacks.
- Latency: client wall clock from sending the POST to receiving the complete envelope, sequential, one warm-up question discarded; columns are p50 / p95 / max in ms. Server latency is `run_metrics.latency_ms`.

### Summary

| Measure | Result |
| --- | --- |
| Single-turn cases correct | 85/107 (79%) |
| Multi-turn scripts fully correct | 19/24 (79%) |
| Multi-turn turns correct | 46/51 (90%) |
| Must-answer (scope.md 7) returned `answered` | 9/9 (100%) |
| V1 `/api/ask` regression (V1 envelope shape + V1 SSE names) | 3/3 (100%) |

### Per intent (single-turn)

Denominators are cases in the section. *Routed* = expected outcome class and intent. *Answered* = status `answered`. *Chart* is over answered cases. *Clarified* = status `clarify` (expected for the clarify and vague sections).

| Section | Cases | Correct | Routed | Answered | Chart (of answered) | Clarified | Latency p50/p95/max ms | Server p50 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| discovery | 10 | 9/10 (90%) | 9/10 (90%) | 9/10 (90%) | 0/9 (0%) | 1/10 (10%) | 12 / 42 / 42 | 4 |
| clarify | 10 | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 0/0 (-) | 10/10 (100%) | 8 / 17 / 17 | 2 |
| descriptive | 10 | 7/10 (70%) | 10/10 (100%) | 10/10 (100%) | 9/10 (90%) | 0/10 (0%) | 26 / 32 / 32 | 20 |
| diagnostic | 14 | 6/14 (43%) | 14/14 (100%) | 14/14 (100%) | 14/14 (100%) | 0/14 (0%) | 330 / 558 / 1565 | 320 |
| impact | 10 | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 22 / 24 / 24 | 15 |
| forecast | 10 | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 14 / 807 / 807 | 8 |
| scenario | 10 | 2/10 (20%) | 9/10 (90%) | 2/10 (20%) | 2/2 (100%) | 1/10 (10%) | 24 / 839 / 839 | 17 |
| prescriptive | 10 | 9/10 (90%) | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 208 / 1130 / 1130 | 201 |
| compound | 10 | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 203 / 658 / 658 | 194 |
| vague | 10 | 10/10 (100%) | 10/10 (100%) | 0/10 (0%) | 0/0 (-) | 10/10 (100%) | 8 / 14 / 14 | 2 |
| v1_regression | 3 | 2/3 (67%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 0/3 (0%) | 20 / 21 / 21 | 15 |
| **all** | 107 | 85/107 (79%) | 105/107 (98%) | 78/107 (73%) | 68/78 (87%) | 22/107 (21%) | 24 / 558 / 1565 | |

### Failure taxonomy (single-turn)

| Section | correct | routing_failure | execution_failure | insufficient_evidence | incorrect_answer |
| --- | --- | --- | --- | --- | --- |
| discovery | 9 | 1 | 0 | 0 | 0 |
| clarify | 10 | 0 | 0 | 0 | 0 |
| descriptive | 7 | 0 | 0 | 0 | 3 |
| diagnostic | 6 | 0 | 0 | 0 | 8 |
| impact | 10 | 0 | 0 | 0 | 0 |
| forecast | 10 | 0 | 0 | 0 | 0 |
| scenario | 2 | 1 | 0 | 7 | 0 |
| prescriptive | 9 | 0 | 0 | 0 | 1 |
| compound | 10 | 0 | 0 | 0 | 0 |
| vague | 10 | 0 | 0 | 0 | 0 |
| v1_regression | 2 | 0 | 0 | 0 | 1 |
| **all** | 85 | 2 | 0 | 7 | 13 |

### Must-answer gate (V2-ANS-2)

| Ref | Question | Status | Category |
| --- | --- | --- | --- |
| D1 | What data do you have? | answered | correct |
| S5 | What are the spikes across all months? | answered | correct |
| G1 | Why did revenue drop in the top category in April 2018? | answered | incorrect_answer |
| I1 | How much did the April 2018 drop cost us? | answered | correct |
| F1 | Forecast revenue for the next 3 months | answered | correct |
| X6 | What if we raise prices 5%? | answered | correct |
| P1 | Which customer segment should we target? | answered | incorrect_answer |
| K1 | How does revenue trend look today and what will it be in 3 months? | answered | correct |
| U1 turn 2 | What about SP? (follow-up) | answered | correct |

### Planted effects (data/SYNTHETIC_GROUND_TRUTH.md)

A diagnostic answer *recovers* a plant when its conclusion or a claim names the planted cause; it *misattributes* when a co-movement claim names the planted confounder instead. Every row reads synthetic tables, so these are results on generated data only.

| Ref | Plant | Question | Status | Recovered | Confounder as driver | Cause tokens found |
| --- | --- | --- | --- | --- | --- | --- |
| G1 | E1 | Why did revenue drop in the top category in April 2018? | answered | no | no | - |
| G3 | E2 | Why did order count fall in December 2017? | answered | no | no | - |
| G4 | E3 | Why did AOV fall in January 2018? | answered | no | no | - |
| G5 | E4 | Why did review scores drop in June 2018? | answered | no | no | - |
| G8 | E1 | Which states drove the revenue decline in May 2018? | answered | no | no | - |
| G10 | E4 | Did the carrier cause the delivery delays? | answered | yes | no | jadlog |
| E-G1s | E1 | Why did web sessions drop in April 2018? | answered | no | no | - |
| E-G3s | E2 | Why did the stockout rate spike in December 2017? | answered | yes | no | stockout |
| E-G4s | E3 | Why did conversion rate rise in January 2018? | answered | no | yes | - |
| E-G5s | E4 | Why did the return rate rise in June 2018? | answered | no | no | - |
| X6 | E5 | What if we raise prices 5%? | answered | yes | no | elasticity |

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
| U8 | 6.2 U8 | 1/2 | FAIL | 2 `What did it add?`: insufficient_evidence - Insufficient history: at least 12 complete consecutive periods are required before the test window. |
| U9 | 6.2 U9 | 1/2 | FAIL | 2 `What if freight rises 10%?`: insufficient_evidence - Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'what if freight rises 10%'  |
| U10 | 6.2 U10 - the third turn inherits from the second; the fourth escalates and keeps RJ | 4/4 | pass | - |
| M-window | 6.1 window shift | 1/2 | FAIL | 2 `And last year?`: incorrect_answer - period 2017-01..2017-08 != 2017-01..2017-12 |
| M-why | 6.1 intent escalation 'Why?' after a change | 2/2 | pass | - |
| M-drill | 6.1 drill-down | 2/2 | pass | - |
| M-grain | 6.1 grain change | 2/2 | pass | - |
| M-metric | 6.1 metric swap | 2/2 | pass | - |
| M-ref | 6.1 reference | 1/2 | FAIL | 2 `Why is that number so low?`: routing_failure - expected ['answer'], got clarify |
| M-forecast-filter | 6.1 intent escalation 'Forecast that' with an inherited filter | 2/2 | pass | - |
| M-why-impact | 6.1 escalation chain: why -> so what | 2/2 | pass | - |
| CL-option | 3.2 C1 - choosing an offered option answers the original question | 2/2 | pass | - |
| CL-default | 3.2 - accepting the stated default answers the question | 1/2 | FAIL | 2 `Use the default`: routing_failure - expected ['answer'], got clarify |
| CL-text | 3.2 C3 - a free-text reply resolves the asked slot | 2/2 | pass | - |
| CL-then-follow | 3.2 + 6.1 - a clarified answer is context for the next follow-up | 3/3 | pass | - |
| RESET | 6.3 rule 1 - after a new topic there is no context to inherit | 3/3 | pass | - |
| COLD | 6.3 rule 1 / C6 - a follow-up with no prior turn clarifies | 1/1 | pass | - |

Turn categories: correct 46, routing_failure 2, execution_failure 0, insufficient_evidence 2, incorrect_answer 1; turn latency p50/p95/max 21 / 419 / 761 ms.

### V1 regression (`POST /api/ask`)

| Question | Status | SSE events | V1 envelope keys | Latency ms |
| --- | --- | --- | --- | --- |
| How many orders were there in August 2018? | answered | answer, step_finished, step_started | match | 25 |
| How did revenue in 2018 compare to 2017? | answered | answer, step_finished, step_started | match | 29 |
| Was order count unusual in August 2018? | answered | answer, step_finished, step_started | match | 23 |

### Every single-turn case

| Ref | Expected | Got | Category | Latency ms | Reason |
| --- | --- | --- | --- | --- | --- |
| D1 | answer/discovery | answered/discovery | correct | 39 | - |
| D2 | answer/discovery | answered/discovery | correct | 12 | - |
| D3 | answer/discovery | answered/discovery | correct | 35 | - |
| D4 | answer/discovery | answered/discovery | correct | 12 | - |
| D5 | answer/discovery | answered/discovery | correct | 9 | - |
| D6 | answer/discovery | answered/discovery | correct | 9 | - |
| D7 | answer/discovery | answered/discovery | correct | 13 | - |
| D8 | answer/discovery | answered/discovery | correct | 42 | - |
| D9 | answer/discovery | answered/discovery | correct | 39 | - |
| D10 | refuse/discovery | clarify/clarify | routing_failure | 9 | expected refuse, got clarify (asked: "I don't hold customer age, customer gender. Would one of these help instead?") |
| C1 | clarify/clarify | clarify/clarify | correct | 17 | - |
| C2 | clarify/clarify | clarify/clarify | correct | 10 | - |
| C3 | clarify/clarify | clarify/clarify | correct | 8 | - |
| C4 | clarify/clarify | clarify/clarify | correct | 8 | - |
| C5 | clarify/clarify | clarify/clarify | correct | 7 | - |
| C6 | clarify/clarify | clarify/clarify | correct | 8 | - |
| C7 | clarify/clarify | clarify/clarify | correct | 8 | - |
| C8 | clarify/clarify | clarify/clarify | correct | 9 | - |
| C9 | clarify/clarify | clarify/clarify | correct | 9 | - |
| C10 | clarify/clarify | clarify/clarify | correct | 9 | - |
| S1 | answer/descriptive | answered/descriptive | correct | 19 | - |
| S2 | answer/descriptive | answered/descriptive | incorrect_answer | 20 | key number 278,162.96 (reference SQL) not in the answer |
| S3 | answer/descriptive | answered/descriptive | correct | 28 | - |
| S4 | answer/descriptive | answered/descriptive | correct | 27 | - |
| S5 | answer/descriptive | answered/descriptive | correct | 17 | - |
| S6 | answer/descriptive | answered/descriptive | correct | 26 | - |
| S7 | answer/descriptive | answered/descriptive | correct | 25 | - |
| S8 | answer/descriptive | answered/descriptive | incorrect_answer | 27 | key number 993.00 (reference SQL) not in the answer |
| S9 | answer/descriptive | answered/descriptive | correct | 29 | - |
| S10 | answer/descriptive | answered/descriptive | incorrect_answer | 32 | key number 2,609,925.47 (reference SQL) not in the answer |
| G1 | answer/diagnostic | answered/diagnostic | incorrect_answer | 307 | planted E1 cause not identified |
| G2 | answer/diagnostic | answered/diagnostic | correct | 204 | - |
| G3 | answer/diagnostic | answered/diagnostic | incorrect_answer | 382 | planted E2 cause not identified |
| G4 | answer/diagnostic | answered/diagnostic | incorrect_answer | 353 | planted E3 cause not identified |
| G5 | answer/diagnostic | answered/diagnostic | incorrect_answer | 190 | planted E4 cause not identified |
| G6 | answer/diagnostic | answered/diagnostic | correct | 384 | - |
| G7 | answer/diagnostic | answered/diagnostic | correct | 211 | - |
| G8 | answer/diagnostic | answered/diagnostic | incorrect_answer | 224 | planted E1 cause not identified |
| G9 | answer/diagnostic | answered/diagnostic | correct | 558 | - |
| G10 | answer/diagnostic | answered/diagnostic | correct | 1565 | - |
| E-G1s | answer/diagnostic | answered/diagnostic | incorrect_answer | 222 | planted E1 cause not identified |
| E-G3s | answer/diagnostic | answered/diagnostic | correct | 380 | - |
| E-G4s | answer/diagnostic | answered/diagnostic | incorrect_answer | 423 | planted E3 cause not identified; E3 confounder reported as the driver: ['boleto'] |
| E-G5s | answer/diagnostic | answered/diagnostic | incorrect_answer | 201 | planted E4 cause not identified |
| I1 | answer/impact | answered/impact | correct | 21 | - |
| I2 | answer/impact | answered/impact | correct | 22 | - |
| I3 | answer/impact | answered/impact | correct | 24 | - |
| I4 | answer/impact | answered/impact | correct | 23 | - |
| I5 | answer/impact | answered/impact | correct | 20 | - |
| I6 | answer/impact | answered/impact | correct | 23 | - |
| I7 | answer/impact | answered/impact | correct | 24 | - |
| I8 | answer/impact | answered/impact | correct | 22 | - |
| I9 | answer/impact | answered/impact | correct | 21 | - |
| I10 | answer/impact | answered/impact | correct | 22 | - |
| F1 | answer/forecast | answered/forecast | correct | 14 | - |
| F2 | answer/forecast | answered/forecast | correct | 14 | - |
| F3 | answer/forecast | answered/forecast | correct | 14 | - |
| F4 | answer/forecast | answered/forecast | correct | 14 | - |
| F5 | answer/forecast | answered/forecast | correct | 807 | - |
| F6 | answer/forecast | answered/forecast | correct | 14 | - |
| F7 | answer/forecast | answered/forecast | correct | 14 | - |
| F8 | answer/forecast | answered/forecast | correct | 13 | - |
| F9 | answer/forecast | answered/forecast | correct | 502 | - |
| F10 | answer/forecast | answered/forecast | correct | 493 | - |
| X1 | answer/scenario | insufficient_evidence/scenario | insufficient_evidence | 23 | Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'what if freight costs rise 10%' has no fitted relationship to perturb, so no figure is  |
| X2 | answer/scenario | answered/scenario | correct | 41 | - |
| X3 | answer/scenario | insufficient_evidence/scenario | insufficient_evidence | 22 | Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'halved' has no fitted relationship to perturb, so no figure is invented. |
| X4 | answer/scenario | insufficient_evidence/scenario | insufficient_evidence | 30 | Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'grew to 85%' has no fitted relationship to perturb, so no figure is invented. |
| X5 | answer/scenario | insufficient_evidence/scenario | insufficient_evidence | 31 | Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'what if aov improved 5%' has no fitted relationship to perturb, so no figure is invente |
| X6 | answer/scenario | answered/scenario | correct | 839 | - |
| X7 | answer/scenario | insufficient_evidence/scenario | insufficient_evidence | 23 | Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'restored the marketing spend we cut' has no fitted relationship to perturb, so no figur |
| X8 | answer/scenario | insufficient_evidence/scenario | insufficient_evidence | 24 | Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'what if order volume grew 10%; but aov fell 5%' has no fitted relationship to perturb,  |
| X9 | answer/scenario | insufficient_evidence/scenario | insufficient_evidence | 24 | Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). 'eliminated the stockouts' has no fitted relationship to perturb, so no figure is invent |
| X10 | refuse/scenario | clarify/clarify | routing_failure | 8 | expected refuse, got clarify (asked: "I don't hold an Argentinian market. Would one of these help instead?") |
| P1 | answer/prescriptive | answered/prescriptive | incorrect_answer | 488 | 0 ranked options, scope.md 3.8 requires 2-3 (REC-3) |
| P2 | answer/prescriptive | answered/prescriptive | correct | 223 | - |
| P3 | answer/prescriptive | answered/prescriptive | correct | 220 | - |
| P4 | answer/prescriptive | answered/prescriptive | correct | 196 | - |
| P5 | answer/prescriptive | answered/prescriptive | correct | 197 | - |
| P6 | answer/prescriptive | answered/prescriptive | correct | 1130 | - |
| P7 | answer/prescriptive | answered/prescriptive | correct | 36 | - |
| P8 | answer/prescriptive | answered/prescriptive | correct | 197 | - |
| P9 | answer/prescriptive | answered/prescriptive | correct | 296 | - |
| P10 | answer/prescriptive | answered/prescriptive | correct | 23 | - |
| K1 | answer/descriptive | answered/descriptive,forecast | correct | 658 | - |
| K2 | answer/diagnostic | answered/diagnostic | correct | 215 | - |
| K3 | answer/diagnostic | answered/diagnostic,impact,prescriptive | correct | 230 | - |
| K4 | answer/descriptive | answered/descriptive,scenario | correct | 47 | - |
| K5 | answer/descriptive | answered/descriptive,forecast | correct | 533 | - |
| K6 | answer/diagnostic | answered/diagnostic,impact | correct | 188 | - |
| K7 | answer/descriptive | answered/descriptive,prescriptive | correct | 30 | - |
| K8 | answer/discovery | answered/discovery,diagnostic | correct | 407 | - |
| K9 | answer/forecast | answered/forecast,scenario | correct | 27 | - |
| K10 | answer/diagnostic | answered/diagnostic,impact,prescriptive | correct | 191 | - |
| V1 | clarify/clarify | clarify/clarify | correct | 9 | - |
| V2 | clarify/clarify | clarify/clarify | correct | 7 | - |
| V3 | clarify/clarify | clarify/clarify | correct | 7 | - |
| V4 | clarify/clarify | clarify/clarify | correct | 14 | - |
| V5 | clarify/clarify | clarify/clarify | correct | 7 | - |
| V6 | clarify/clarify | clarify/clarify | correct | 11 | - |
| V7 | clarify/clarify | clarify/clarify | correct | 8 | - |
| V8 | clarify/clarify | clarify/clarify | correct | 8 | - |
| V9 | clarify/clarify | clarify/clarify | correct | 7 | - |
| V10 | clarify/clarify | clarify/clarify | correct | 8 | - |
| R-1 | answer/descriptive | answered/descriptive | correct | 19 | - |
| R-2 | answer/descriptive | answered/descriptive | correct | 20 | - |
| R-3 | answer/descriptive | answered/descriptive | incorrect_answer | 21 | key number 46,131.75 (reference SQL) not in the answer |

<!-- END GENERATED: scripts/eval_v2.py -->
