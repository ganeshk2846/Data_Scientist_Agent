"""Every governed metric declares its aggregation (build plan acceptance 1.8)."""

from __future__ import annotations

import re

import pytest

from catalog.registry import MetricRegistry
from semantic.aggregation import AggregationRegistry, MetricAggregation, MetricComponent


def _squash(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_every_registry_metric_has_exactly_one_aggregation():
    metrics = MetricRegistry.default()
    aggregations = AggregationRegistry()

    assert set(aggregations.metric_ids()) == {m.metric_id for m in metrics.metrics}
    assert len(aggregations) == len(metrics) == 9


@pytest.mark.parametrize(
    ("metric_id", "expected"),
    [
        ("revenue", "sum"),
        ("gmv", "sum"),
        ("freight_value", "sum"),
        ("item_count", "sum"),
        ("order_count", "count"),
        ("customer_count", "count"),
        ("review_score", "mean"),
        ("aov", "ratio"),
        ("cancellation_rate", "ratio"),
    ],
)
def test_aggregation_class(metric_id, expected):
    assert AggregationRegistry().require(metric_id).aggregation == expected


def test_ratio_components_are_the_metrics_own_parts():
    metrics = MetricRegistry.default()
    for metric_id in ("aov", "cancellation_rate"):
        entry = AggregationRegistry().require(metric_id)
        formula = _squash(metrics.require(metric_id).formula)
        assert _squash(entry.numerator.formula) in formula
        assert _squash(entry.denominator.formula) in formula


def test_mean_decomposes_into_sum_over_count():
    entry = AggregationRegistry().require("review_score")
    formula = MetricRegistry.default().require("review_score").formula

    column = re.search(r"AVG\((.+)\)", formula).group(1)
    assert entry.numerator.formula == f"SUM({column})"
    assert entry.denominator.formula == f"COUNT({column})"
    assert entry.bounds == (1.0, 5.0)


def test_non_additive_without_parts_is_rejected():
    with pytest.raises(ValueError, match="numerator and denominator"):
        MetricAggregation(metric_id="aov", aggregation="ratio")


def test_additive_with_parts_is_rejected():
    part = MetricComponent(name="x", formula="SUM(x)", aggregation="sum")
    with pytest.raises(ValueError, match="additive"):
        MetricAggregation(metric_id="revenue", aggregation="sum", numerator=part)


def test_unknown_metric_and_duplicates_fail_closed():
    with pytest.raises(KeyError):
        AggregationRegistry().require("profit")
    entry = MetricAggregation(metric_id="revenue", aggregation="sum")
    with pytest.raises(ValueError, match="duplicate"):
        AggregationRegistry([entry, entry])
