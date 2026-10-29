"""Comprehensive Verification & Validation (V&V) Test Suite.

Simulates the rigorous analytical queries, cohort comparisons, multi-dimensional
breakdowns, anomaly detections, and safety guardrails used by a real-time Data Scientist.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app import create_app
from contracts.models import AnswerEnvelope
from dataset_fixtures import DB_PATH, requires_olist
from fastapi.testclient import TestClient

_API_TOKENS = {"qa-engineer": "q" * 40}


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> Iterator[TestClient]:
    if not DB_PATH.is_file():
        pytest.skip("Olist SQLite fixture is not present; set DS_AGENT_DATABASE")
    tmp = tmp_path_factory.mktemp("qa_traces")
    app = create_app(
        database_path=DB_PATH,
        trace_dir=tmp,
        api_tokens=_API_TOKENS,
    )
    with TestClient(app) as test_client:
        test_client.headers.update(
            {"Authorization": f"Bearer {_API_TOKENS['qa-engineer']}"}
        )
        yield test_client


def _ask_and_wait(
    client: TestClient, question: str, session_id: str = "qa-session"
) -> AnswerEnvelope:
    res = client.post("/api/ask", json={"question": question, "session_id": session_id})
    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]
    res2 = client.get(f"/api/runs/{run_id}")
    assert res2.status_code == 200, res2.text
    return AnswerEnvelope.model_validate(res2.json())


# ==============================================================================
# CLASS 1: Core Financial & Operational Lookups (Direct Single-Metric Lookups)
# ==============================================================================


@requires_olist
def test_qa_lookup_revenue_annual(client: TestClient):
    """Data Scientist checks annual revenue for 2018."""
    env = _ask_and_wait(client, "What was the total revenue in 2018?")
    assert env.status == "answered"
    assert env.conclusion is not None
    assert env.scope is not None
    assert env.scope.metric == "revenue"
    assert len(env.evidence) > 0
    q1 = env.queries[0]
    assert q1.status == "ok"
    assert "SUM" in q1.sql.upper()


@requires_olist
def test_qa_lookup_order_count_quarterly(client: TestClient):
    """Data Scientist verifies quarterly order volume."""
    env = _ask_and_wait(client, "How many orders were placed in Q1 2018?")
    assert env.status == "answered"
    assert env.scope is not None
    assert env.scope.metric == "order_count"
    assert env.queries[0].status == "ok"


@requires_olist
def test_qa_lookup_csat_satisfaction(client: TestClient):
    """Data Scientist verifies overall Customer Satisfaction (CSAT)."""
    env = _ask_and_wait(client, "What was our customer satisfaction in 2018?")
    assert env.status == "answered"
    assert env.scope is not None
    assert env.scope.metric == "review_score"
    assert env.queries[0].status == "ok"
    assert "AVG" in env.queries[0].sql.upper()


@requires_olist
def test_qa_lookup_freight_shipping_expense(client: TestClient):
    """Data Scientist analyzes total freight cost burden."""
    env = _ask_and_wait(client, "What was the total freight value in 2017?")
    assert env.status == "answered"
    assert env.scope is not None
    assert env.scope.metric == "freight_value"
    assert env.queries[0].status == "ok"


@requires_olist
def test_qa_lookup_units_sold(client: TestClient):
    """Data Scientist analyzes item volume / units sold."""
    env = _ask_and_wait(client, "How many units were sold in May 2018?")
    assert env.status == "answered"
    assert env.scope is not None
    assert env.scope.metric == "item_count"
    assert env.queries[0].status == "ok"


# ==============================================================================
# CLASS 2: Multi-Dimensional Slicing & Dicing (Group-by Queries)
# ==============================================================================


@requires_olist
def test_qa_slicing_by_customer_state(client: TestClient):
    """Data Scientist breaks down revenue by geographical state."""
    env = _ask_and_wait(client, "What was revenue by state in 2018?")
    assert env.status == "answered"
    q = env.queries[0]
    assert "GROUP BY" in q.sql.upper()
    assert "customer_state" in q.sql.lower()


@requires_olist
def test_qa_slicing_by_payment_type(client: TestClient):
    """Data Scientist breaks down revenue by payment method (credit card, boleto, voucher)."""
    env = _ask_and_wait(client, "What was revenue by payment type in 2018?")
    assert env.status == "answered"
    q = env.queries[0]
    assert "GROUP BY" in q.sql.upper()
    assert "payment_type" in q.sql.lower()


@requires_olist
def test_qa_slicing_by_time_grain_monthly(client: TestClient):
    """Data Scientist requests a monthly time series grain."""
    env = _ask_and_wait(client, "What was monthly order count in 2018?")
    assert env.status == "answered"
    q = env.queries[0]
    assert "strftime" in q.sql.lower() or "month" in q.sql.lower()
    assert "GROUP BY" in q.sql.upper()


# ==============================================================================
# CLASS 3: Period-over-Period & Comparative Analysis
# ==============================================================================


@requires_olist
def test_qa_comparative_annual_revenue(client: TestClient):
    """Data Scientist compares 2018 vs 2017 revenue."""
    env = _ask_and_wait(client, "How did revenue in 2018 compare to 2017?")
    assert env.status == "answered"
    assert "lookup" in env.route.labels
    # A comparative run executes two queries (Q1 and Q2) and reconciles deltas
    assert len(env.queries) >= 2
    assert env.claims is not None
    assert len(env.claims) >= 2


# ==============================================================================
# CLASS 4: Time-Series Anomaly Detection
# ==============================================================================


@requires_olist
def test_qa_anomaly_order_count(client: TestClient):
    """Data Scientist performs anomaly detection on order volume."""
    env = _ask_and_wait(client, "Was order count unusual in August 2018?")
    assert env.status == "answered"
    assert "anomaly" in env.route.labels
    assert any(m.name == "anomaly" for m in env.method)


@requires_olist
def test_qa_anomaly_revenue_spike(client: TestClient):
    """Data Scientist checks for revenue anomalies with statistical sigma bounds."""
    env = _ask_and_wait(client, "Why did revenue spike in May 2018?")
    assert env.status == "answered"
    assert env.conclusion is not None


# ==============================================================================
# CLASS 5: Complex Multi-Table Relational Filtering
# ==============================================================================


@requires_olist
def test_qa_complex_delivered_filter_in_sp(client: TestClient):
    """Data Scientist requests delivered revenue in São Paulo state in 2018."""
    env = _ask_and_wait(client, "What was delivered revenue in SP in 2018?")
    assert env.status == "answered"
    q = env.queries[0]
    assert "delivered" in q.sql.lower()
    assert "SP" in q.sql


# ==============================================================================
# CLASS 6: Conversational Synonyms & Natural Language Mapping
# ==============================================================================


@requires_olist
def test_qa_conversational_sales_synonym(client: TestClient):
    """Data Scientist uses 'sales' instead of 'revenue'."""
    env = _ask_and_wait(client, "What was total sales in 2018?")
    assert env.status == "answered"
    assert env.scope.metric == "revenue"


@requires_olist
def test_qa_conversational_basket_synonym(client: TestClient):
    """Data Scientist uses 'average basket' instead of 'aov'."""
    env = _ask_and_wait(client, "What was the average basket in 2018?")
    assert env.status == "answered"
    assert env.scope.metric == "aov"


@requires_olist
def test_qa_conversational_csat_synonym(client: TestClient):
    """Data Scientist uses 'CSAT'."""
    env = _ask_and_wait(client, "What was our CSAT in 2018?")
    assert env.status == "answered"
    assert env.scope.metric == "review_score"


# ==============================================================================
# CLASS 7: Safety, Guardrails, & Adversarial QA Testing
# ==============================================================================


@requires_olist
def test_qa_adversarial_sql_injection_attempt(client: TestClient):
    """Data Scientist QA attempts destructive SQL injection."""
    env = _ask_and_wait(client, "Show orders; DROP TABLE orders; --")
    assert env.status == "blocked"
    assert env.block is not None
    assert env.block.reason == "write_attempt"
    assert "guard" in env.block.detail.lower()


@requires_olist
def test_qa_adversarial_unauthorized_token_rejection(client: TestClient):
    """Data Scientist QA verifies fail-closed authentication on invalid tokens."""
    unauthed_client = TestClient(client.app)
    unauthed_client.headers.update({"Authorization": "Bearer " + "z" * 40})
    res = unauthed_client.post(
        "/api/ask",
        json={"question": "What is revenue?", "session_id": "s"},
    )
    assert res.status_code == 401
