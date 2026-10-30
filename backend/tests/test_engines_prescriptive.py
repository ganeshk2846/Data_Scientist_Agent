"""Prescriptive engine: k-means segments, LP reorder allocation, ranked actions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from contracts.v2 import SegmentResult
from engine_helpers import assert_complete_report, data, stable, table

from engines import prescriptive
from engines.prescriptive import optimize_reorder


def _states():
    rng = np.random.default_rng(4)
    rows = []
    for index, state in enumerate(("SP", "RJ", "MG", "BA", "PE", "CE", "PR", "SC", "RS")):
        south = state in {"PR", "SC", "RS"}
        rows.append((state, (5.0 if south else 0.0) + rng.normal(0, 0.3), (0.4 if south else 0.05) + rng.normal(0, 0.01),
                     20.0 + index))
    return pd.DataFrame(rows, columns=["state", "delay_days", "breach_rate", "freight"])


def test_kmeans_segments_report_members_that_match_the_kmeans_assignment():
    run = prescriptive.execute({"mode": "segments", "entity": "states", "key": "state", "n_clusters": 2},
                               data({"states": table(_states(), "Q-STATES", state="key")}, seed=5))
    assert run.result.tool == "python.segment"
    result = run.result.analyst_output.result
    assert isinstance(result, SegmentResult) and result.mode == "rank_segments"
    members = dict(run.report.table("membership").rows)
    assert members["PR"] == members["SC"] == members["RS"]
    assert members["SP"] != members["PR"]
    sizes = {cluster.cluster: cluster.size for cluster in result.clusters}
    assert sizes[members["PR"]] == 3
    assert_complete_report(run.report)


def _items():
    return pd.DataFrame({
        "item": ["a", "b", "c", "d"],
        "forecast_demand": [100.0, 50.0, 80.0, 20.0],
        "stock_on_hand": [0.0, 60.0, 10.0, 0.0],
        "unit_cost": [10.0, 5.0, 8.0, 20.0],
        "unit_margin": [4.0, 3.0, 6.0, 2.0],
    })


def test_reorder_lp_maximises_margin_under_the_budget_and_spends_only_what_covers_demand():
    plan = optimize_reorder(_items(), budget=900.0)
    by_item = plan.set_index("item")
    assert plan["order_cost"].sum() <= 900.0 + 1e-6
    # c has the best margin per R$ (6/8), then a (4/10); d is worst (2/20) and b is already covered.
    assert by_item.loc["c", "order_units"] == pytest.approx(70.0, abs=1e-4)
    assert by_item.loc["a", "order_units"] == pytest.approx((900.0 - 70 * 8.0) / 10.0, abs=1e-4)
    assert by_item.loc["b", "order_units"] == pytest.approx(0.0, abs=1e-6)
    assert by_item.loc["d", "order_units"] == pytest.approx(0.0, abs=1e-6)
    generous = optimize_reorder(_items(), budget=10000.0)
    assert generous["order_cost"].sum() == pytest.approx(100 * 10 + 70 * 8 + 20 * 20, rel=1e-6)
    assert (generous["fill_rate"] > 0.999).all()


def test_reorder_mode_ranks_the_optimizer_against_simple_policies():
    run = prescriptive.execute({"mode": "reorder", "budget": 900.0}, data({"items": table(_items(), "Q-ITEMS")}, seed=2))
    result = run.result.analyst_output.result
    assert result.mode == "rank_actions" and 2 <= len(result.actions) <= 3
    assert result.actions[0].action_id == "optimized_reorder"
    assert all(option.trade_offs and option.assumptions for option in result.actions)
    policies = {row[0]: row[1] for row in run.report.table("policies").rows}
    assert policies["optimized_reorder"] >= max(policies["proportional_reorder"], policies["close_gaps_first"]) - 1e-6
    assert run.report.number("margin_gain_vs_proportional") >= 0
    assert_complete_report(run.report)
    assert stable(run.result) == stable(prescriptive.execute({"mode": "reorder", "budget": 900.0},
                                                             data({"items": table(_items(), "Q-ITEMS")}, seed=2)).result)


def test_actions_mode_reuses_rank_actions_with_budget_allocation():
    actions = pd.DataFrame({
        "action_id": ["restock", "promo", "survey"],
        "title": ["Restock", "Run promo", "Survey customers"],
        "expected_impact": [500.0, 300.0, 50.0],
        "cost": [100.0, 200.0, 10.0],
        "evidence_grade": [3, 2, 1],
        "kind": ["intervention", "intervention", "information_gathering"],
        "assumptions": ["Demand holds", "Margin covers discount", "Response rate 10%"],
        "trade_offs": ["Ties up cash", "Erodes price perception", "Slow"],
        "sensitivity": ["Demand -20% halves gain", "Elasticity", "Response rate"],
        "monitor": ["Fill rate", "Margin", "Responses"],
        "data_that_would_change_ranking": ["Lead times", "Elasticity estimate", "Prior survey"],
    })
    run = prescriptive.execute({"mode": "actions", "budget": 250.0, "evidence_grades": (3, 2)},
                               data({"actions": table(actions, "Q-ACTIONS", action_id="key")}))
    result = run.result.analyst_output.result
    assert result.budget_allocation
    assert all(0.0 <= fraction <= 1.0 + 1e-9 for _, fraction in result.budget_allocation)
    funded = dict(result.budget_allocation)
    costs = {"restock": 100.0, "promo": 200.0, "survey": 10.0}
    assert sum(costs[name] * fraction for name, fraction in funded.items()) <= 250.0 + 1e-6
    assert run.report.table("budget_allocation").rows
    assert_complete_report(run.report)


def test_reorder_without_a_budget_is_insufficient():
    run = prescriptive.execute({"mode": "reorder"}, data({"items": table(_items(), "Q-ITEMS")}))
    assert run.result.status == "insufficient_evidence"
