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


@pytest.fixture(scope="module")
def runner(v2_build):
    from context import ContextStore
    from service import RunService, build_runtime
    from service_v2 import V2Runner

    service = RunService(lambda: build_runtime(v2_build["db"], reasoning_client=False))
    v2 = V2Runner(service, contexts=ContextStore())
    yield v2
    v2.close()
    service.close()


def test_impact_after_a_spike_sizes_against_the_previous_month_when_no_expected_value_fits(runner):
    """scope.md 6.2 U8: too little history for an expected value is a reason to use the plainer baseline."""
    runner.run_sync("Why did revenue spike in Nov 2017?", session_id="fx-u8")
    _, envelope = runner.run_sync("What did it add?", session_id="fx-u8")
    assert envelope.status == "answered"
    assert envelope.intent.intents[0].intent == "impact"
    assert "against the baseline" in envelope.conclusion
    assert any("sized against the previous window instead" in item for item in envelope.assumptions)


def test_a_judgement_about_the_prior_figure_is_answered_against_the_year_before(runner):
    """scope.md 6.1 reference shape; a bare 'Why?' after a single total still clarifies (U2)."""
    runner.run_sync("What was the average review score in 2018?", session_id="fx-ref")
    _, envelope = runner.run_sync("Why is that number so low?", session_id="fx-ref")
    assert envelope.status == "answered"
    assert envelope.intent.intents[0].intent == "diagnostic"
    assert envelope.resolved_question.comparison_period.start.year == 2017
    assert envelope.resolved_question.inherited_fields
    runner.run_sync("What was the average review score in 2018?", session_id="fx-u2")
    _, bare = runner.run_sync("Why?", session_id="fx-u2")
    assert bare.status == "clarify"


def test_accepting_the_default_answers_instead_of_asking_about_a_window_that_was_always_open(runner):
    """scope.md 3.2: round 2 only for an ambiguity the reply introduced; otherwise the stated default applies."""
    run_id, first = runner.run_sync("How are sales doing?", session_id="fx-cl")
    assert first.status == "clarify" and first.clarification.slot == "metric"
    _, second = runner.run_sync("ok", session_id="fx-cl", clarification_of=run_id,
                                option_id=first.clarification.default_assumption.option_id)
    assert second.status == "answered"
    assert second.resolved_question.metric_id == "revenue"
    assert any("default was used" in item for item in second.assumptions)  # never silent (CL-4)


@pytest.mark.parametrize(("question", "sql", "expected_text"), [
    ("What was revenue in 2017?",
     ("SELECT SUM(p.payment_value) FROM order_payments p JOIN orders o ON o.order_id = p.order_id "
      "WHERE o.order_status NOT IN ('canceled','unavailable') AND o.order_purchase_timestamp >= '2017-01-01' "
      "AND o.order_purchase_timestamp < '2018-01-01'"), "Revenue for 2017-01 to 2017-12 was"),
    ("How many unique customers ordered in Q2 2018?",
     ("SELECT COUNT(DISTINCT c.customer_unique_id) FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
      "WHERE o.order_purchase_timestamp >= '2018-04-01' AND o.order_purchase_timestamp < '2018-07-01'"), "for 2018-04 to 2018-06 was"),
])
def test_a_window_question_states_the_governed_total_for_the_window(pipeline, v2_build, question, sql, expected_text):
    import sqlite3

    with sqlite3.connect(f"file:{v2_build['db']}?mode=ro", uri=True) as conn:
        expected = conn.execute(sql).fetchone()[0]
    envelope = pipeline.run(question, run_id="fx-total").envelope
    assert envelope.status == "answered"
    assert expected_text in envelope.conclusion
    assert any(abs(value - expected) < 0.01 for value in _numbers(envelope))  # measured, not summed from months


def test_a_single_month_states_its_value_without_a_zero_change_trend(pipeline):
    envelope = pipeline.run("How many orders were there in August 2018?", run_id="fx-month").envelope
    assert envelope.conclusion.startswith("Order count for 2018-08 was")
    assert "moved from" not in envelope.conclusion


def test_the_segment_question_ranks_two_to_three_options_without_new_figures(pipeline):
    """scope.md 3.8 P1 (must-answer) and REC-3: options with assumptions, trade-offs, what to monitor."""
    envelope = pipeline.run("Which customer segment should we target?", run_id="fx-p1").envelope
    assert envelope.status == "answered"
    assert 2 <= len(envelope.next_actions) <= 3
    assert [option.rank for option in envelope.next_actions] == list(range(1, len(envelope.next_actions) + 1))
    for option in envelope.next_actions:
        assert option.assumptions and option.trade_offs and option.monitor and option.data_that_would_change_ranking
        assert not re.search(r"\d+\.\d|R\$", option.title)  # SAFE-8: options cite segments by rank, figures stay in claims


def test_shock_measurements_compose_by_product_and_bound_recovered_cancellations():
    from engines.prep import shock_measurements

    outcome, frame = shock_measurements({"revenue": 1000.0}, [("order_count", 1.10), ("aov", 0.95)])
    assert outcome == "revenue" and frame.loc[0, "baseline"] == 1000.0
    assert abs(frame.loc[0, "current"] - 1000.0 * 1.10 * 0.95) < 1e-9
    _, frame = shock_measurements({"revenue": 1000.0, "cancellation_rate": 0.02, "order_count": 500.0, "aov": 50.0},
                                  [("cancellation_rate", 0.5)])
    assert abs(frame.loc[0, "current"] - (1000.0 + 0.5 * 0.02 * 500.0 * 50.0)) < 1e-9
    with pytest.raises(ValueError):
        shock_measurements({"revenue": 1.0, "freight_value": 1.0}, [("aov", 1.1), ("freight_value", 1.1)])


def test_a_stated_multiplier_is_applied_to_the_measured_baseline_and_labelled_mechanical(pipeline, v2_build):
    """scope.md X8: two shocks composed by the engine, not multiplied in prose; no fitted response is claimed."""
    import sqlite3

    with sqlite3.connect(f"file:{v2_build['db']}?mode=ro", uri=True) as conn:
        revenue = conn.execute(
            "SELECT SUM(p.payment_value) FROM order_payments p JOIN orders o ON o.order_id = p.order_id "
            "WHERE o.order_status NOT IN ('canceled','unavailable') AND o.order_purchase_timestamp >= '2018-06-01' "
            "AND o.order_purchase_timestamp < '2018-09-01'").fetchone()[0]
    envelope = pipeline.run("What if order volume grew 10% but AOV fell 5%?", run_id="fx-x8").envelope
    assert envelope.status == "answered"
    assert "not a fitted response" in envelope.conclusion
    numbers = _numbers(envelope)
    assert any(abs(value - round(revenue, 2)) < 0.01 for value in numbers)
    assert any(abs(value - round(revenue * 1.10 * 0.95, 2)) < 0.01 for value in numbers)
    unsupported = pipeline.run("What if we eliminated the stockouts?", run_id="fx-x9").envelope
    assert unsupported.status == "insufficient_evidence"  # an absolute target has no measured multiplier to apply


def test_a_two_window_comparison_names_both_windows_and_keeps_acronyms(pipeline):
    """'Revenue for total was ... against the comparison window' read as a template; the windows are the answer."""
    compare = pipeline.run("How did revenue in 2018 compare to 2017?", run_id="fx-cmp").envelope
    assert compare.status == "answered"
    assert compare.conclusion.startswith("Revenue for 2018-01 to 2018-08 was")
    assert "against 2017-01 to 2017-08" in compare.conclusion and "for total" not in compare.conclusion
    why = pipeline.run("Why did revenue drop in the top category in April 2018?", run_id="fx-gmv").envelope
    assert why.conclusion.startswith("GMV was") and "Gmv" not in why.conclusion
    assert "co-moved significantly" not in why.conclusion  # says which test found nothing (the full-history correlation)
