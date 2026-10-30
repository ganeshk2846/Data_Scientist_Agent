"""Tests for catalog-backed discovery service answers (SAFE-8, scope.md section 3.1)."""

from semantic.discovery import DiscoveryService


def test_d1_lists_all_19_tables_with_synthetic_labels():
    service = DiscoveryService()
    ans = service.answer_discovery("What tables do you have?")
    assert ans["status"] == "ok"
    assert "19 tables" in ans["narrative"]
    assert ans["tables_count"] == 19

    facts = {f.key: f.value for f in ans["facts_payload"].facts}
    assert "orders" in facts
    assert facts["orders"]["is_synthetic"] is False
    assert "marketing_spend" in facts
    assert facts["marketing_spend"]["is_synthetic"] is True


def test_d2_date_range_declares_truncation():
    service = DiscoveryService()
    ans = service.answer_discovery("What date range is covered?")
    assert ans["status"] == "ok"
    assert "2018-08" in ans["narrative"]
    assert "2016-09-04" in ans["narrative"]


def test_d3_metrics_returns_aggregations():
    service = DiscoveryService()
    ans = service.answer_discovery("What metrics are available?")
    assert ans["status"] == "ok"
    facts = {f.key: f.value for f in ans["facts_payload"].facts}
    assert "revenue" in facts
    assert facts["revenue"]["aggregation"] == "sum"
    assert "aov" in facts
    assert facts["aov"]["aggregation"] == "ratio"


def test_d6_customer_count():
    service = DiscoveryService()
    ans = service.answer_discovery("How many customers are in the dataset?")
    assert ans["status"] == "ok"
    assert "99,441" in ans["narrative"]
    assert "96,096" in ans["narrative"]


def test_d7_customer_segments_primary_key():
    service = DiscoveryService()
    ans = service.answer_discovery("What is the primary key of customer_segments?")
    assert ans["status"] == "ok"
    assert "customer_unique_id" in ans["narrative"]


def test_d10_safe_refusal_for_credit_score():
    service = DiscoveryService()
    ans = service.answer_discovery(
        "Do you have customer demographic survey or credit score data?"
    )
    assert ans["status"] == "refused"
    assert "credit score" in ans["narrative"]
    assert "income" in ans["narrative"]
