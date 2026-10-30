"""Discovery route (Track 4): tables, metrics and example questions from the catalog, with no generated SQL."""

from __future__ import annotations

import re

import pytest
from semantic.discovery import asks_for_metric_list, example_questions, table_mentioned

pytestmark = pytest.mark.filterwarnings("ignore::ResourceWarning")


@pytest.fixture(scope="module")
def pipeline(v2_build):
    from pipeline_v2 import PipelineV2
    from service import build_runtime

    runtime = build_runtime(v2_build["db"], reasoning_client=False)
    yield PipelineV2(guard=runtime.guard, catalog=runtime.catalog, manager=runtime.manager)
    runtime.close()


@pytest.mark.parametrize(("question", "table"), [
    ("What is in order_items?", "order_items"),
    ("what's in the order items table", "order_items"),
    ("Describe the marketing_spend table", "marketing_spend"),
    ("Which columns does order_payments have?", "order_payments"),
    ("Tell me about the customers table", "customers"),
    ("How many orders were placed in 2018?", None),
    ("What was revenue in SP in July 2018?", None),
    ("What is in the top category?", None),
])
def test_table_mentioned_needs_a_registered_name_and_a_structural_cue(question, table):
    assert table_mentioned(question) == table


def test_metric_list_questions_and_digit_free_examples():
    assert asks_for_metric_list("Which metrics can I ask about?")
    assert asks_for_metric_list("what KPIs do you have")
    assert not asks_for_metric_list("What was revenue last month?")
    examples = example_questions("revenue")
    assert examples and all(not re.search(r"\d", question) for question in examples)
    assert example_questions("not_a_metric") == ()


def test_what_is_in_order_items_is_answered_from_the_catalog(pipeline):
    outcome = pipeline.run("What is in order_items?")
    envelope = outcome.envelope
    assert envelope.status == "answered" and envelope.intent.intent_names == ("discovery",)
    assert envelope.route.labels == ("lookup",)
    assert [(step.tool, step.params["lookup"]) for step in envelope.plan.steps] == [("catalog", "table")]
    assert envelope.queries == ()  # no generated SQL
    conclusion = envelope.conclusion
    assert "order_items is a real Olist table" in conclusion and "rows" in conclusion
    assert "Its columns are" in conclusion and "price" in conclusion and "freight_value" in conclusion
    assert "gmv" in conclusion and "You could ask" in conclusion
    # Every figure in the answer is a ledger claim (SAFE-8, acceptance 1.16).
    approved = {number.token for claim in envelope.claims for number in claim.numbers}
    assert all(token in approved for token in re.findall(r"\d[\d,]*", conclusion))


def test_a_synthetic_table_is_labelled_in_the_answer_and_its_provenance(pipeline):
    envelope = pipeline.run("Describe the marketing_spend table").envelope
    assert envelope.status == "answered"
    assert "synthetic (generated, not real business)" in envelope.conclusion
    assert any("marketing_spend" in caveat for caveat in envelope.caveats)  # SY-1


def test_which_metrics_lists_real_and_synthetic_metrics_with_examples(pipeline):
    envelope = pipeline.run("Which metrics can I ask about?").envelope
    assert envelope.status == "answered" and envelope.intent.intent_names == ("discovery",)
    assert [step.params["lookup"] for step in envelope.plan.steps] == ["metrics"]
    assert envelope.queries == ()
    assert "governed metrics" in envelope.conclusion and "synthetic" in envelope.conclusion
    assert "revenue" in envelope.conclusion and "Try:" in envelope.conclusion


def test_what_data_do_you_have_still_uses_the_warehouse_overview(pipeline):
    envelope = pipeline.run("What data do you have?").envelope
    assert envelope.status == "answered"
    assert [step.params["lookup"] for step in envelope.plan.steps] == ["warehouse"]


def test_ordinary_questions_about_orders_are_not_captured(pipeline):
    envelope = pipeline.run("How many orders were placed in 2018?").envelope
    assert envelope.intent.intent_names[0] == "descriptive"
