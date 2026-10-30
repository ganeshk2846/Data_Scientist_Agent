"""Every governed metric declares its aggregation (build plan acceptance 1.8)."""

from __future__ import annotations

import re

import pytest

from catalog.registry import MetricRegistry
from semantic.aggregation import AggregationRegistry, MetricAggregation, MetricComponent
from semantic.metrics_v2 import SYNTHETIC_METRIC_IDS, all_metrics


def _squash(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_every_registry_metric_has_exactly_one_aggregation():
    metrics = all_metrics()
    aggregations = AggregationRegistry()

    assert set(aggregations.metric_ids()) == {m.metric_id for m in metrics.metrics}
    assert len(MetricRegistry.default()) == 9
    assert len(aggregations) == len(metrics) == 16


def test_synthetic_kpis_are_registered_and_labelled():
    assert SYNTHETIC_METRIC_IDS == {
        "marketing_spend",
        "sessions",
        "conversion_rate",
        "stockout_rate",
        "return_rate",
        "margin",
        "target_attainment",
    }
    for metric_id in SYNTHETIC_METRIC_IDS:
        metric = all_metrics().require(metric_id)
        assert any("synthetic" in caveat.lower() for caveat in metric.caveats)
        assert MetricRegistry.default().get(metric_id) is None


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
        ("marketing_spend", "sum"),
        ("sessions", "sum"),
        ("conversion_rate", "ratio"),
        ("stockout_rate", "ratio"),
        ("return_rate", "ratio"),
        ("margin", "ratio"),
        ("target_attainment", "ratio"),
    ],
)
def test_aggregation_class(metric_id, expected):
    assert AggregationRegistry().require(metric_id).aggregation == expected


def test_ratio_components_are_the_metrics_own_parts():
    metrics = all_metrics()
    ratios = [m for m in AggregationRegistry().metric_ids() if AggregationRegistry().require(m).aggregation == "ratio"]
    assert len(ratios) == 7
    for metric_id in ratios:
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
