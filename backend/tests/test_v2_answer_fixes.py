"""End-to-end regressions for the fixes found by scripts/eval_v2.py (docs/EVAL_V2.md).

Each test runs the real V2 pipeline on the seeded V2 build; no step is mocked.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture(scope="module")
def pipeline(v2_build):
    from pipeline_v2 import PipelineV2
    from service import build_runtime

    runtime = build_runtime(v2_build["db"], reasoning_client=False)
    yield PipelineV2(guard=runtime.guard, catalog=runtime.catalog, manager=runtime.manager)
    runtime.close()


def _numbers(envelope) -> set[float]:
    return {number.value for claim in envelope.claims for number in claim.numbers}


def test_a_precomputed_forecast_states_its_anchor_and_every_month(pipeline):
    envelope = pipeline.run("Forecast revenue for the next 3 months", run_id="fx-1").envelope
    assert envelope.status == "answered"
    assert "Anchored on 2018-08, the last complete month" in envelope.conclusion  # V2-DATA-2
    assert "2018-09 to 2018-11" in envelope.conclusion
    assert "Month by month:" in envelope.conclusion
    for token in re.findall(r"\b20\d\d\b", envelope.conclusion):
        assert float(token) in _numbers(envelope), token  # every figure stays in the ledger (SAFE-3)


def test_a_bounded_horizon_names_the_limit_instead_of_shrinking_silently(pipeline):
    envelope = pipeline.run("What will revenue be in 2020?", run_id="fx-2").envelope
    assert envelope.status == "answered"
    assert "periods were asked for; the history supports" in envelope.conclusion  # scope.md F9
    assert "Anchored on 2018-08" in envelope.conclusion
