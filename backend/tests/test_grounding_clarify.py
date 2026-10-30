"""Grounding and clarification: unknown terms clarify, never refuse; 2-round cap (RQ, CL-1..7)."""

from __future__ import annotations

import clarify
import pytest
from grounding import Grounder
from intent import IntentExtractor
from semantic.metrics_v2 import all_metrics


@pytest.fixture(scope="module")
def tools():
    return IntentExtractor(), Grounder(all_metrics())


def _ground(tools, question, **kwargs):
    extractor, grounder = tools
    return grounder.ground(extractor.extract(question), **kwargs)


def test_summarize_revenue_clarifies_the_window_with_a_default_never_refuses(tools):
    grounded = _ground(tools, "Summarize revenue")
    request = grounded.clarification
    assert grounded.intent.intent_names == ("clarify",)
    assert request.slot == "period" and 2 <= len(request.options) <= 4 and request.question.count("?") == 1
    default = next(option for option in request.options if option.option_id == request.default_assumption.option_id)
    assert default.label == "Last 12 complete months" and default.recommended
    assert default.resolves_to["period"] == {"start": "2017-09-01", "end": "2018-09-01"}


def test_choosing_an_option_is_deterministic_and_resolves(tools):
    request = _ground(tools, "Summarize revenue").clarification
    first = _ground(tools, "Summarize revenue", patch=clarify.patch_for(request, "O2")[0], round_number=2, of_run_id="r1")
    second = _ground(tools, "Summarize revenue", patch=clarify.patch_for(request, "O2")[0], round_number=2, of_run_id="r1")
    assert first.resolved == second.resolved and first.clarification is None
    assert first.resolved.metric_id == "revenue" and first.resolved.period.start.isoformat() == "2018-01-01"


def test_a_third_round_is_never_asked_the_default_is_used_and_recorded(tools):
    grounded = _ground(tools, "How's business?", round_number=3, of_run_id="r2")
    assert grounded.clarification is None
    assert grounded.resolved.metric_id == "revenue"
    assert any("default was used" in note for note in grounded.resolved.assumptions)


def test_gross_versus_net_revenue_is_asked_not_guessed(tools):
    request = _ground(tools, "What was gross revenue in 2018?").clarification
    assert request.slot == "metric"
    assert {option.resolves_to["metric_id"] for option in request.options} == {"gmv", "revenue"}


def test_attributes_that_do_not_exist_are_named_with_answerable_alternatives(tools):
    request = _ground(tools, "Do you have customer age or gender?").clarification
    assert "age" in request.what_understood and "gender" in request.what_understood
    assert all("effective_text" in option.resolves_to for option in request.options)


def test_risk_questions_get_suggestions_not_a_dead_end(tools):
    request = _ground(tools, "Which customers are likely to churn?").clarification
    assert request.slot == "intent" and "no risk score is invented" in request.what_understood.lower()
    assert any("cancellation" in option.label.lower() for option in request.options)


def test_a_disallowed_breakdown_switches_to_the_governed_sibling_and_says_so(tools):
    grounded = _ground(tools, "Why did revenue drop in the top category in April 2018?")
    assert grounded.resolved.metric_id == "gmv"
    assert any("cannot be split by product_category" in note for note in grounded.resolved.assumptions)


def test_defaults_are_recorded_in_plain_words(tools):
    grounded = _ground(tools, "What was revenue in 2018?")
    assert any("clipped" in note for note in grounded.resolved.assumptions)
    forecast = _ground(tools, "Forecast revenue")
    assert any("No horizon was stated" in note for note in forecast.resolved.assumptions)


def test_every_clarification_offers_two_to_four_options_and_one_question(tools):
    for question in ("Show growth", "Tell me about SP", "Anything unusual?", "What about last month?", "Is freight expensive?",
                     "What if we launched in Argentina?", "Why did it drop?"):
        request = _ground(tools, question).clarification
        assert request is not None, question
        assert 2 <= len(request.options) <= 4 and request.question.count("?") == 1, question
        assert request.default_assumption.option_id in {option.option_id for option in request.options}, question
