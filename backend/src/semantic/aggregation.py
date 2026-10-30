"""How each governed metric aggregates (build plan Track 1, work item 4).

A share-of-change decomposition is only valid for additive metrics. Forcing
one onto a mean or a ratio silently breaks ``DRV-2`` reconciliation, so every
metric declares its aggregation class, and every non-additive metric declares
the additive parts it is built from. The driver engine decomposes those parts
(``scope.md`` G4, G9) and the forecast engine projects them (F4).

The metadata lives beside the V1 registry rather than inside
``MetricDefinition``: that model is a V1 contract and stays unchanged. A test
holds the two in step - every registry metric has exactly one entry here, and
each component formula appears in the metric's own formula.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field, model_validator

from contracts.models import ContractModel, MetricDefinition

AggregationClass = Literal["sum", "count", "mean", "ratio"]


class MetricComponent(ContractModel):
    """One additive part of a non-additive metric, in registry template SQL."""

    name: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    aggregation: Literal["sum", "count"]


class MetricAggregation(ContractModel):
    metric_id: str = Field(min_length=1)
    aggregation: AggregationClass
    numerator: MetricComponent | None = None
    denominator: MetricComponent | None = None
    bounds: tuple[float, float] | None = None

    @property
    def is_additive(self) -> bool:
        return self.aggregation in ("sum", "count")

    @model_validator(mode="after")
    def _parts_match_class(self) -> MetricAggregation:
        has_parts = self.numerator is not None and self.denominator is not None
        if self.is_additive and (self.numerator or self.denominator):
            raise ValueError(
                f"{self.metric_id}: an additive metric has no numerator/denominator"
            )
        if not self.is_additive and not has_parts:
            raise ValueError(
                f"{self.metric_id}: a {self.aggregation} metric must declare "
                "its numerator and denominator"
            )
        if self.bounds is not None and self.bounds[0] >= self.bounds[1]:
            raise ValueError(f"{self.metric_id}: bounds must be (low, high)")
        return self


_PAID_ORDERS = MetricComponent(
    name="paid_order_count",
    formula="COUNT(DISTINCT {{ orders }}.order_id)",
    aggregation="count",
)

_AGGREGATIONS: tuple[MetricAggregation, ...] = (
    MetricAggregation(metric_id="gmv", aggregation="sum"),
    MetricAggregation(metric_id="revenue", aggregation="sum"),
    MetricAggregation(metric_id="freight_value", aggregation="sum"),
    MetricAggregation(metric_id="item_count", aggregation="sum"),
    MetricAggregation(metric_id="order_count", aggregation="count"),
    MetricAggregation(metric_id="customer_count", aggregation="count"),
    MetricAggregation(
        metric_id="review_score",
        aggregation="mean",
        numerator=MetricComponent(
            name="review_score_total",
            formula="SUM({{ order_reviews }}.review_score)",
            aggregation="sum",
        ),
        denominator=MetricComponent(
            name="review_count",
            formula="COUNT({{ order_reviews }}.review_score)",
            aggregation="count",
        ),
        bounds=(1.0, 5.0),
    ),
    MetricAggregation(
        metric_id="aov",
        aggregation="ratio",
        numerator=MetricComponent(
            name="payment_value",
            formula="SUM({{ order_payments }}.payment_value)",
            aggregation="sum",
        ),
        denominator=_PAID_ORDERS,
    ),
    MetricAggregation(
        metric_id="cancellation_rate",
        aggregation="ratio",
        numerator=MetricComponent(
            name="canceled_order_count",
            formula=(
                "SUM(CASE WHEN {{ orders }}.order_status = 'canceled' "
                "THEN 1.0 ELSE 0.0 END)"
            ),
            aggregation="count",
        ),
        denominator=MetricComponent(
            name="order_count",
            formula="COUNT({{ orders }}.order_id)",
            aggregation="count",
        ),
        bounds=(0.0, 1.0),
    ),
)


class AggregationRegistry:
    """Closed lookup of aggregation metadata by ``metric_id``."""

    def __init__(self, entries: Iterable[MetricAggregation] = _AGGREGATIONS) -> None:
        by_id: dict[str, MetricAggregation] = {}
        for entry in entries:
            if entry.metric_id in by_id:
                raise ValueError(f"duplicate aggregation for {entry.metric_id!r}")
            by_id[entry.metric_id] = entry
        self._by_id = by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, metric_id: str) -> MetricAggregation | None:
        return self._by_id.get(metric_id)

    def require(self, metric_id: str) -> MetricAggregation:
        entry = self._by_id.get(metric_id)
        if entry is None:
            raise KeyError(f"no aggregation declared for metric {metric_id!r}")
        return entry

    def for_metric(self, metric: MetricDefinition) -> MetricAggregation:
        return self.require(metric.metric_id)

    def metric_ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)


__all__ = [
    "AggregationClass",
    "AggregationRegistry",
    "MetricAggregation",
    "MetricComponent",
]
