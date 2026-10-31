"""Intent and entity extraction: rules first, model only as a tie-break (RTE-2)."""

from __future__ import annotations

from datetime import date

import pytest
from intent import EntityExtractor, IntentExtractor, read_time, split_clauses


class FakeClient:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def chat_json(self, messages):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload, None


def test_compound_question_yields_one_scored_intent_per_clause_with_spans():
    result = IntentExtractor().extract("How does revenue trend look today and what will it be in 3 months?")
    assert [item.intent for item in result.intents] == ["descriptive", "forecast"]
    assert result.intents[0].span and "trend" in result.intents[0].span
    assert result.intents[1].span and "3 months" in result.intents[1].span
    assert result.entities.horizon.periods == 3 and result.entities.horizon.anchor == "2018-08"
    assert split_clauses("Was August unusual, and why?") == ["Was August unusual", "why"]


def test_the_model_is_not_consulted_when_rules_decide():
    client = FakeClient({"intents": ["scenario"], "confidence": 0.9})
    result = IntentExtractor(client=client).extract("Forecast revenue for the next 3 months")
    assert client.calls == 0
    assert [item.intent for item in result.intents] == ["forecast"]
    assert result.signals.model is None


def test_the_model_breaks_a_tie_only_when_no_rule_fires_and_is_code_validated():
    client = FakeClient({"intents": ["forecast", "made_up_intent"], "confidence": 0.8})
    result = IntentExtractor(client=client).extract("revenue outlook")
    assert client.calls == 1
    assert [item.intent for item in result.intents] == ["forecast"], "unknown intents are dropped"
    assert result.signals.model.proposed == ("forecast",)


def test_an_unavailable_model_never_blocks_a_question():
    client = FakeClient(error=ConnectionError("ollama is down"))
    result = IntentExtractor(client=client).extract("revenue outlook")
    assert client.calls == 1
    assert result.intents == ()
    assert result.signals.model is not None and result.signals.model.proposed == ()


@pytest.mark.parametrize(
    ("question", "metric"),
    [("What was GMV by customer state in 2018?", "gmv"), ("reveune in 2017", "revenue"), ("How many orders in 2017?", "order_count"),
     ("average order value by state", "aov"), ("What was marketing spend by channel in 2018?", "marketing_spend")],
)
def test_metrics_are_grounded_on_registry_synonyms_with_fuzzy_matching(question, metric):
    mentions = EntityExtractor().mentions(question)
    assert mentions and mentions[0].metric_id == metric


def test_dimension_phrases_are_not_read_as_metrics():
    mentions = EntityExtractor().mentions("What was GMV by customer state in 2018?")
    assert [item.metric_id for item in mentions] == ["gmv"]


def test_filters_come_from_the_value_index_only():
    extractor = EntityExtractor()
    found = {item.dimension: item.values for item in extractor.values.link("revenue in SP and the south for boleto via jadlog")}
    assert found["customer_state"] == ("SP", "PR", "SC", "RS")
    assert found["payment_type"] == ("boleto",)
    assert found["carrier"] == ("jadlog",)
    assert extractor.values.link("revenue in ZZ") == []


def test_time_is_clipped_to_the_last_complete_month_and_says_so():
    reading = read_time("What was revenue in 2018?", anchor="2018-08")
    assert (reading.period.start, reading.period.end) == (date(2018, 1, 1), date(2018, 9, 1))
    assert any("clipped" in note for note in reading.assumptions)
    compared = read_time("How did revenue in 2018 compare to 2017?", anchor="2018-08")
    assert compared.comparison.start == date(2017, 1, 1) and compared.comparison.end == date(2017, 9, 1)
    assert any("aligned" in note for note in compared.assumptions)
    bare = read_time("Was August unusual?", anchor="2018-08")
    assert bare.period.start == date(2018, 8, 1)


def test_scenario_parameters_are_extracted_without_inventing_coefficients():
    extractor = EntityExtractor()
    price = extractor.scenario_params("What if we raise prices 5%?", None)
    assert [(item.target, item.kind, item.value) for item in price] == [("price", "multiplicative", 1.05)]
    lose = extractor.scenario_params("What if we lose SP entirely?", "revenue")
    assert lose[0].kind == "remove" and lose[0].applies_to.values == ("SP",)
    halved = extractor.scenario_params("What if the cancellation rate halved?", "cancellation_rate")
    assert halved[0].value == 0.5


def test_extraction_is_deterministic():
    first = IntentExtractor().extract("Why did revenue drop in the top category in April 2018?")
    second = IntentExtractor().extract("Why did revenue drop in the top category in April 2018?")
    assert first.intents == second.intents and first.entities == second.entities
