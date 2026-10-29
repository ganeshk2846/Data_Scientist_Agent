# BE-2 local scale report

Generated: 2026-10-29T15:37:57.648322+00:00
Environment: Python 3.13.2; Windows-11-10.0.26300-SP0
Seed: 7; encoder: signed-word-char-ngram-v1

| Tables | Generate (s) | Onboard (s) | Dense vectors | Self-test | Status |
|---:|---:|---:|---:|:---:|:---|
| 50 | 0.021 | 1.340 | 248 | passed | needs_review |
| 200 | 0.027 | 2.432 | 998 | passed | needs_review |
| 500 | 0.045 | 4.682 | 2498 | passed | needs_review |

Reproduce with:

```text
python -m src.onboarding.scale_report --sizes 50 200 500
```

## Limitations

- Single local run per size. Not an SLA, benchmark, or production cost measurement.
- Local elapsed time only; no cloud spend or provider pricing was measured.
- Temporary warehouses and truth directories are removed after each run.
