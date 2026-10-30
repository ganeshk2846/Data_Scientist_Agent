from __future__ import annotations

from analysts.segment import SegmentAnalyst
from contracts.models import AnalystColumn, AnalystInput, TableRef
from contracts.v2 import SegmentResult


def _table(names, rows, *, query_id="Q-SEGMENT"):
    columns = tuple(
        AnalystColumn(
            name=name,
            type="TEXT" if name in {"customer_unique_id", "state", "action_id", "title", "kind", "assumptions", "trade_offs", "sensitivity", "monitor", "data_that_would_change_ranking"} else "REAL",
            role="key" if name == "customer_unique_id" else "dimension" if name in {"state", "kind"} else "measure",
        )
        for name in names
    )
    return TableRef(
        query_id=query_id,
        columns=columns,
        row_count=len(rows),
        uri=f"inline://{query_id}",
        rows=tuple(tuple(row) for row in rows),
    )


def test_kmeans_segmentation_is_seeded_and_returns_measured_profiles():
    rows = tuple(
        (
            f"customer-{index}",
            "SP" if index % 2 == 0 else "RJ",
            float(index * 10 + (index % 3)),
            float(index + 1),
        )
        for index in range(20)
    )
    table = _table(
        ("customer_unique_id", "state", "ltv", "orders"),
        rows,
    )
    analyst_input = AnalystInput(
        module="segment",
        params={"mode": "rank_segments", "n_clusters": 3},
        tables={"customers": table},
        run_id="RUN-SEGMENTS",
        seed=17,
    )
    analyst = SegmentAnalyst()

    first = analyst.run(analyst_input)
    second = analyst.run(analyst_input)

    assert first.status == "ok"
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert isinstance(first.result, SegmentResult)
    assert first.result.mode == "rank_segments"
    assert len(first.result.clusters) == 3
    assert sum(cluster.size for cluster in first.result.clusters) == 20
    assert all(cluster.profile for cluster in first.result.clusters)


def test_rank_actions_returns_complete_ranked_options_and_budget_allocation():
    rows = (
        ("act-a", "Improve checkout", 120.0, 5.0, 3, "Margin holds", "Discount cost", "Elasticity varies", "Conversion", "New margin data", "intervention"),
        ("act-b", "Repair stock feed", 100.0, 4.0, 2, "Inventory is accurate", "Engineering effort", "Stockout rate varies", "Stockout rate", "Inventory audit", "intervention"),
        ("act-c", "Run customer research", 20.0, 2.0, 2, "Survey response is representative", "Time to result", "Response rate varies", "Responses", "Customer interviews", "information_gathering"),
    )
    table = _table(
        (
            "action_id",
            "title",
            "expected_impact",
            "cost",
            "evidence_grade",
            "assumptions",
            "trade_offs",
            "sensitivity",
            "monitor",
            "data_that_would_change_ranking",
            "kind",
        ),
        rows,
        query_id="Q-ACTIONS",
    )
    output = SegmentAnalyst().run(
        AnalystInput(
            module="segment",
            params={"mode": "rank_actions", "max_options": 3, "budget": 7.0},
            tables={"actions": table},
            run_id="RUN-ACTIONS",
            seed=2,
        )
    )

    assert output.status == "ok"
    assert output.result.mode == "rank_actions"
    assert len(output.result.actions) == 3
    assert tuple(action.rank for action in output.result.actions) == (1, 2, 3)
    assert all(action.assumptions and action.trade_offs for action in output.result.actions)
    assert all(action.sensitivity and action.monitor for action in output.result.actions)
    assert all(action.data_that_would_change_ranking for action in output.result.actions)
    assert output.result.action_impacts
    assert output.result.budget_allocation
    assert sum(fraction * dict((row[0], row[3]) for row in rows)[action_id] for action_id, fraction in output.result.budget_allocation) <= 7.0 + 1e-8


def test_low_evidence_ranks_only_supplied_information_gathering_actions():
    rows = (
        ("info-a", "Interview customers", 8.0, 1.0, 0, "Sample is representative", "Time", "Response rate", "Interview count", "New survey", "information_gathering"),
        ("info-b", "Audit stock data", 7.0, 2.0, 0, "Records are complete", "Analyst time", "Coverage", "Missing rows", "Inventory scan", "information_gathering"),
        ("act-a", "Increase discount", 90.0, 5.0, 1, "Demand responds", "Margin loss", "Elasticity", "Net revenue", "Experiment result", "intervention"),
    )
    table = _table(
        (
            "action_id",
            "title",
            "expected_impact",
            "cost",
            "evidence_grade",
            "assumptions",
            "trade_offs",
            "sensitivity",
            "monitor",
            "data_that_would_change_ranking",
            "kind",
        ),
        rows,
    )
    output = SegmentAnalyst().run(
        AnalystInput(
            module="segment",
            params={
                "mode": "rank_actions",
                "evidence_grades": (0, 1),
                "max_options": 2,
            },
            tables={"actions": table},
            run_id="RUN-INFO-ACTIONS",
            seed=0,
        )
    )

    assert output.status == "ok"
    assert len(output.result.actions) == 2
    assert all(action.kind == "information_gathering" for action in output.result.actions)
    assert output.result.actions[0].action_id == "info-a"


def test_segment_empty_and_sparse_data_returns_insufficient_evidence():
    missing = SegmentAnalyst().run(
        AnalystInput(
            module="segment",
            params={"mode": "rank_segments"},
            run_id="RUN-EMPTY",
        )
    )
    assert missing.status == "insufficient_evidence"

    single_row = _table(
        ("customer_unique_id", "ltv"),
        (("customer-1", 10.0),),
    )
    sparse = SegmentAnalyst().run(
        AnalystInput(
            module="segment",
            params={"mode": "rank_segments"},
            tables={"customers": single_row},
            run_id="RUN-SPARSE",
        )
    )
    assert sparse.status == "insufficient_evidence"
    assert sparse.result is None
