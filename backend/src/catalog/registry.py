"""In-code governed metric registry for the deterministic fast path (MET-1)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from contracts.models import (
    MetricAllowedDimension,
    MetricDefinition,
    MetricJoinPath,
    MetricReconciliation,
)

_APPROVED_AT = "2026-10-25T00:00:00Z"
_APPROVED_BY = "seed-registry"

_ITEM_ORDERS = MetricJoinPath(
    edge_id="order_items.order_id=orders.order_id",
    cardinality="N:1",
)
_PAYMENT_ORDERS = MetricJoinPath(
    edge_id="order_payments.order_id=orders.order_id",
    cardinality="N:1",
)
_CUSTOMER_ORDERS = MetricJoinPath(
    edge_id="customers.customer_id=orders.customer_id",
    cardinality="1:N",
)
_ITEM_PRODUCTS = MetricJoinPath(
    edge_id="order_items.product_id=products.product_id",
    cardinality="N:1",
)
_REVIEW_ORDERS = MetricJoinPath(
    edge_id="order_reviews.order_id=orders.order_id",
    cardinality="N:1",
)
_SELLER_ITEMS = MetricJoinPath(
    edge_id="order_items.seller_id=sellers.seller_id",
    cardinality="N:1",
)

_COMPLETED_ORDER_FILTER = "{{ orders }}.order_status NOT IN ('canceled', 'unavailable')"


def _state_dimension(*edges: str) -> MetricAllowedDimension:
    return MetricAllowedDimension(
        name="customer_state",
        column="customer_state",
        table="customers",
        join_edges=tuple(edges),
        synonyms=("state", "customer state", "customer states", "region"),
    )


def _city_dimension(*edges: str) -> MetricAllowedDimension:
    return MetricAllowedDimension(
        name="customer_city",
        column="customer_city",
        table="customers",
        join_edges=tuple(edges),
        synonyms=("city", "customer city", "town"),
    )


def _seller_state_dimension(*edges: str) -> MetricAllowedDimension:
    return MetricAllowedDimension(
        name="seller_state",
        column="seller_state",
        table="sellers",
        join_edges=tuple(edges),
        synonyms=("seller state", "seller region", "origin state"),
    )


def _status_dimension(*edges: str) -> MetricAllowedDimension:
    return MetricAllowedDimension(
        name="order_status",
        column="order_status",
        table="orders",
        join_edges=tuple(edges),
        synonyms=("status", "order status", "order statuses"),
    )


def _month_dimension(*edges: str) -> MetricAllowedDimension:
    return MetricAllowedDimension(
        name="month",
        column="order_purchase_timestamp",
        table="orders",
        join_edges=tuple(edges),
        synonyms=("month", "monthly", "by month"),
        time_grain="month",
    )


def _year_dimension(*edges: str) -> MetricAllowedDimension:
    return MetricAllowedDimension(
        name="year",
        column="order_purchase_timestamp",
        table="orders",
        join_edges=tuple(edges),
        synonyms=("year", "yearly", "by year"),
        time_grain="year",
    )


def _default_metrics() -> tuple[MetricDefinition, ...]:
    return (
        MetricDefinition(
            metric_id="gmv",
            name="Gross Merchandise Value",
            aggregation="sum",
            completeness_rule="volume_drop_trailing_median",
            synonyms=(
                "gmv",
                "gross merchandise value",
                "gross merchandise volume",
                "merchandise value",
            ),
            formula=("SUM({{ order_items }}.price + {{ order_items }}.freight_value)"),
            required_filters=(_COMPLETED_ORDER_FILTER,),
            grain=("order_item",),
            date_column="orders.order_purchase_timestamp",
            allowed_dimensions=(
                _state_dimension(
                    _ITEM_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _city_dimension(
                    _ITEM_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _status_dimension(_ITEM_ORDERS.edge_id),
                MetricAllowedDimension(
                    name="product_category",
                    column="product_category_name",
                    table="products",
                    join_edges=(_ITEM_PRODUCTS.edge_id,),
                    synonyms=("category", "product category", "product categories"),
                ),
                _seller_state_dimension(_SELLER_ITEMS.edge_id),
                _month_dimension(_ITEM_ORDERS.edge_id),
                _year_dimension(_ITEM_ORDERS.edge_id),
            ),
            base_table="order_items",
            join_path=(_ITEM_ORDERS, _CUSTOMER_ORDERS, _ITEM_PRODUCTS, _SELLER_ITEMS),
            reconciliation=MetricReconciliation(
                sql=(
                    "SELECT SUM(oi.price + oi.freight_value) "
                    "FROM order_items oi "
                    "JOIN orders o ON oi.order_id = o.order_id "
                    "WHERE o.order_status NOT IN ('canceled', 'unavailable')"
                ),
                tolerance=0.01,
            ),
            caveats=(
                (
                    "GMV includes item price and freight for non-canceled, "
                    "non-unavailable orders."
                ),
            ),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="revenue",
            name="Revenue",
            synonyms=(
                "revenue",
                "total revenue",
                "sales",
                "total sales",
                "net sales",
                "net total sales",
                "net total revenue",
                "turnover",
            ),
            formula="SUM({{ order_payments }}.payment_value)",
            required_filters=(_COMPLETED_ORDER_FILTER,),
            grain=("order",),
            date_column="orders.order_purchase_timestamp",
            allowed_dimensions=(
                _state_dimension(
                    _PAYMENT_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _city_dimension(
                    _PAYMENT_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _status_dimension(_PAYMENT_ORDERS.edge_id),
                MetricAllowedDimension(
                    name="payment_type",
                    column="payment_type",
                    table="order_payments",
                    synonyms=("payment type", "payment method", "payment types"),
                ),
                _month_dimension(_PAYMENT_ORDERS.edge_id),
                _year_dimension(_PAYMENT_ORDERS.edge_id),
            ),
            base_table="order_payments",
            join_path=(_PAYMENT_ORDERS, _CUSTOMER_ORDERS),
            reconciliation=MetricReconciliation(
                sql=(
                    "SELECT SUM(op.payment_value) "
                    "FROM order_payments op "
                    "JOIN orders o ON op.order_id = o.order_id "
                    "WHERE o.order_status NOT IN ('canceled', 'unavailable')"
                ),
                tolerance=0.01,
            ),
            caveats=("Revenue uses recorded payment value, not item list price.",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="order_count",
            name="Order Count",
            aggregation="count",
            completeness_rule="volume_drop_trailing_median",
            synonyms=(
                "order count",
                "order volume",
                "number of orders",
                "how many orders",
            ),
            formula="COUNT(DISTINCT {{ orders }}.order_id)",
            required_filters=(),
            grain=("order",),
            date_column="orders.order_purchase_timestamp",
            allowed_dimensions=(
                _state_dimension(_CUSTOMER_ORDERS.edge_id),
                _city_dimension(_CUSTOMER_ORDERS.edge_id),
                _status_dimension(),
                _month_dimension(),
                _year_dimension(),
            ),
            base_table="orders",
            join_path=(_CUSTOMER_ORDERS,),
            reconciliation=MetricReconciliation(
                sql="SELECT COUNT(DISTINCT order_id) FROM orders",
                tolerance=0.0,
            ),
            caveats=("All order statuses are included.",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="aov",
            name="Average Order Value",
            aggregation="ratio",
            numerator_metric="revenue",
            denominator_metric="order_count",
            completeness_rule="volume_drop_trailing_median",
            synonyms=(
                "aov",
                "average order value",
                "average basket",
                "average order size",
                "average order amount",
            ),
            formula=(
                "SUM({{ order_payments }}.payment_value) * 1.0 "
                "/ NULLIF(COUNT(DISTINCT {{ orders }}.order_id), 0)"
            ),
            required_filters=(_COMPLETED_ORDER_FILTER,),
            grain=("order",),
            date_column="orders.order_purchase_timestamp",
            allowed_dimensions=(
                _state_dimension(
                    _PAYMENT_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _city_dimension(
                    _PAYMENT_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _status_dimension(_PAYMENT_ORDERS.edge_id),
                MetricAllowedDimension(
                    name="payment_type",
                    column="payment_type",
                    table="order_payments",
                    synonyms=("payment type", "payment method", "payment types"),
                ),
                _month_dimension(_PAYMENT_ORDERS.edge_id),
                _year_dimension(_PAYMENT_ORDERS.edge_id),
            ),
            base_table="order_payments",
            join_path=(_PAYMENT_ORDERS, _CUSTOMER_ORDERS),
            reconciliation=MetricReconciliation(
                sql=(
                    "SELECT SUM(op.payment_value) * 1.0 "
                    "/ NULLIF(COUNT(DISTINCT o.order_id), 0) "
                    "FROM order_payments op "
                    "JOIN orders o ON op.order_id = o.order_id "
                    "WHERE o.order_status NOT IN ('canceled', 'unavailable')"
                ),
                tolerance=0.01,
            ),
            caveats=("AOV divides recorded payment value by distinct paid orders.",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="review_score",
            name="Customer Satisfaction Score",
            aggregation="mean",
            completeness_rule="volume_drop_trailing_median",
            synonyms=(
                "csat",
                "customer satisfaction",
                "customer rating",
                "customer ratings",
                "satisfaction score",
                "satisfaction rating",
            ),
            formula="AVG({{ order_reviews }}.review_score)",
            required_filters=(),
            grain=("review",),
            date_column="orders.order_purchase_timestamp",
            allowed_dimensions=(
                _state_dimension(
                    _REVIEW_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _city_dimension(
                    _REVIEW_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _status_dimension(_REVIEW_ORDERS.edge_id),
                _month_dimension(_REVIEW_ORDERS.edge_id),
                _year_dimension(_REVIEW_ORDERS.edge_id),
            ),
            base_table="order_reviews",
            join_path=(_REVIEW_ORDERS, _CUSTOMER_ORDERS),
            reconciliation=MetricReconciliation(
                sql="SELECT AVG(review_score) FROM order_reviews",
                tolerance=0.01,
            ),
            caveats=("Average review score across rated orders (1 to 5 scale).",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="freight_value",
            name="Freight Value",
            aggregation="sum",
            completeness_rule="volume_drop_trailing_median",
            synonyms=(
                "freight",
                "freight value",
                "freight cost",
                "shipping cost",
                "delivery fee",
                "shipping fee",
                "total freight",
            ),
            formula="SUM({{ order_items }}.freight_value)",
            required_filters=(_COMPLETED_ORDER_FILTER,),
            grain=("order_item",),
            date_column="orders.order_purchase_timestamp",
            allowed_dimensions=(
                _state_dimension(
                    _ITEM_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _city_dimension(
                    _ITEM_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _status_dimension(_ITEM_ORDERS.edge_id),
                MetricAllowedDimension(
                    name="product_category",
                    column="product_category_name",
                    table="products",
                    join_edges=(_ITEM_PRODUCTS.edge_id,),
                    synonyms=("category", "product category", "product categories"),
                ),
                _seller_state_dimension(_SELLER_ITEMS.edge_id),
                _month_dimension(_ITEM_ORDERS.edge_id),
                _year_dimension(_ITEM_ORDERS.edge_id),
            ),
            base_table="order_items",
            join_path=(_ITEM_ORDERS, _CUSTOMER_ORDERS, _ITEM_PRODUCTS, _SELLER_ITEMS),
            reconciliation=MetricReconciliation(
                sql=(
                    "SELECT SUM(oi.freight_value) "
                    "FROM order_items oi "
                    "JOIN orders o ON oi.order_id = o.order_id "
                    "WHERE o.order_status NOT IN ('canceled', 'unavailable')"
                ),
                tolerance=0.01,
            ),
            caveats=(
                "Freight value represents total shipping charge for completed orders.",
            ),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="item_count",
            name="Item Count",
            aggregation="count",
            completeness_rule="volume_drop_trailing_median",
            synonyms=(
                "item count",
                "units sold",
                "units were sold",
                "units",
                "quantity sold",
                "number of items",
                "total items",
                "volume of items",
                "items sold",
                "how many units",
            ),
            formula="COUNT({{ order_items }}.order_item_id)",
            required_filters=(_COMPLETED_ORDER_FILTER,),
            grain=("order_item",),
            date_column="orders.order_purchase_timestamp",
            allowed_dimensions=(
                _state_dimension(
                    _ITEM_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _city_dimension(
                    _ITEM_ORDERS.edge_id,
                    _CUSTOMER_ORDERS.edge_id,
                ),
                _status_dimension(_ITEM_ORDERS.edge_id),
                MetricAllowedDimension(
                    name="product_category",
                    column="product_category_name",
                    table="products",
                    join_edges=(_ITEM_PRODUCTS.edge_id,),
                    synonyms=("category", "product category", "product categories"),
                ),
                _seller_state_dimension(_SELLER_ITEMS.edge_id),
                _month_dimension(_ITEM_ORDERS.edge_id),
                _year_dimension(_ITEM_ORDERS.edge_id),
            ),
            base_table="order_items",
            join_path=(_ITEM_ORDERS, _CUSTOMER_ORDERS, _ITEM_PRODUCTS, _SELLER_ITEMS),
            reconciliation=MetricReconciliation(
                sql=(
                    "SELECT COUNT(oi.order_item_id) "
                    "FROM order_items oi "
                    "JOIN orders o ON oi.order_id = o.order_id "
                    "WHERE o.order_status NOT IN ('canceled', 'unavailable')"
                ),
                tolerance=0.0,
            ),
            caveats=(
                "Item count measures individual purchased units in non-canceled orders.",
            ),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="customer_count",
            name="Unique Customers",
            aggregation="count",
            completeness_rule="volume_drop_trailing_median",
            synonyms=(
                "unique customers",
                "customer count",
                "active customers",
                "buyer count",
                "number of customers",
                "customer volume",
                "distinct buyers",
            ),
            formula="COUNT(DISTINCT {{ customers }}.customer_unique_id)",
            required_filters=(),
            grain=("customer",),
            date_column="orders.order_purchase_timestamp",
            allowed_dimensions=(
                _state_dimension(),
                _city_dimension(),
                _month_dimension(_CUSTOMER_ORDERS.edge_id),
                _year_dimension(_CUSTOMER_ORDERS.edge_id),
            ),
            base_table="customers",
            join_path=(_CUSTOMER_ORDERS,),
            reconciliation=MetricReconciliation(
                sql="SELECT COUNT(DISTINCT customer_unique_id) FROM customers",
                tolerance=0.0,
            ),
            caveats=("Counts distinct customer_unique_id entities.",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="cancellation_rate",
            name="Cancellation Rate",
            aggregation="ratio",
            numerator_metric="canceled_orders",
            denominator_metric="order_count",
            completeness_rule="volume_drop_trailing_median",
            synonyms=(
                "cancellation rate",
                "canceled rate",
                "order cancellation rate",
                "cancelled rate",
                "churn rate",
            ),
            formula=(
                "SUM(CASE WHEN {{ orders }}.order_status = 'canceled' THEN 1.0 ELSE 0.0 END) "
                "/ NULLIF(COUNT({{ orders }}.order_id), 0)"
            ),
            required_filters=(),
            grain=("order",),
            date_column="orders.order_purchase_timestamp",
            allowed_dimensions=(
                _state_dimension(_CUSTOMER_ORDERS.edge_id),
                _city_dimension(_CUSTOMER_ORDERS.edge_id),
                _month_dimension(),
                _year_dimension(),
            ),
            base_table="orders",
            join_path=(_CUSTOMER_ORDERS,),
            reconciliation=MetricReconciliation(
                sql=(
                    "SELECT SUM(CASE WHEN order_status = 'canceled' THEN 1.0 ELSE 0.0 END) "
                    "/ COUNT(order_id) FROM orders"
                ),
                tolerance=0.001,
            ),
            caveats=(
                "Cancellation rate calculates canceled orders divided by total orders placed.",
            ),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="marketing_spend",
            name="Marketing Spend",
            synonyms=(
                "marketing spend",
                "ad spend",
                "marketing investment",
                "advertising cost",
            ),
            formula="SUM({{ marketing_spend }}.spend)",
            required_filters=(),
            grain=("day", "channel"),
            date_column="marketing_spend.date",
            base_table="marketing_spend",
            aggregation="sum",
            is_synthetic=True,
            caveats=("Synthetic operational marketing spend indicator.",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="sessions",
            name="Web Sessions",
            synonyms=("web sessions", "traffic", "visits", "sessions"),
            formula="SUM({{ web_traffic }}.sessions)",
            required_filters=(),
            grain=("day", "channel"),
            date_column="web_traffic.date",
            base_table="web_traffic",
            aggregation="sum",
            is_synthetic=True,
            caveats=("Synthetic digital traffic session volume.",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="conversion_rate",
            name="Conversion Rate",
            synonyms=("conversion rate", "cvr", "session conversion rate"),
            formula="AVG({{ web_traffic }}.conversion_rate)",
            required_filters=(),
            grain=("day", "channel"),
            date_column="web_traffic.date",
            base_table="web_traffic",
            aggregation="ratio",
            numerator_metric="order_count",
            denominator_metric="sessions",
            is_synthetic=True,
            caveats=("Synthetic web conversion efficiency.",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="stockout_rate",
            name="Stockout Rate",
            synonyms=("stockout rate", "out of stock rate", "stockout frequency"),
            formula="SUM({{ inventory_daily }}.stockout_flag) * 1.0 / NULLIF(COUNT(*), 0)",
            required_filters=(),
            grain=("day", "product"),
            date_column="inventory_daily.date",
            base_table="inventory_daily",
            aggregation="ratio",
            is_synthetic=True,
            caveats=("Synthetic inventory availability metric.",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="return_rate",
            name="Return Rate",
            synonyms=("return rate", "refund rate", "returns percentage"),
            formula="COUNT({{ returns }}.order_item_id) * 1.0 / NULLIF(COUNT(DISTINCT {{ order_items }}.order_item_id), 0)",
            required_filters=(),
            grain=("day",),
            date_column="returns.return_date",
            base_table="returns",
            aggregation="ratio",
            is_synthetic=True,
            caveats=("Synthetic customer merchandise return rate.",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
        MetricDefinition(
            metric_id="target_attainment",
            name="Regional Target Attainment",
            synonyms=("target attainment", "quota attainment", "target achievement"),
            formula="AVG({{ regional_targets }}.target_value)",
            required_filters=(),
            grain=("month", "state"),
            date_column="regional_targets.month",
            base_table="regional_targets",
            aggregation="ratio",
            is_synthetic=True,
            caveats=("Synthetic regional performance quota attainment.",),
            approved_by=_APPROVED_BY,
            approved_at=_APPROVED_AT,
        ),
    )


def _normalize(text: str) -> str:
    lowered = text.lower().replace("&", " and ")
    lowered = re.sub(r"[_\-/]+", " ", lowered)
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    return " ".join(lowered.split())


def _contains(question: str, phrase: str) -> bool:
    if not phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", question) is not None


class MetricRegistry:
    """Deterministic synonym registry for governed metric definitions."""

    def __init__(self, metrics: Iterable[MetricDefinition] = ()) -> None:
        entries = tuple(metrics)
        by_id: dict[str, MetricDefinition] = {}
        for metric in entries:
            key = metric.metric_id.lower()
            if key in by_id:
                raise ValueError(f"duplicate metric_id: {metric.metric_id}")
            by_id[key] = metric
        self._metrics = entries
        self._by_id = by_id

    @classmethod
    def default(cls) -> MetricRegistry:
        return cls(_default_metrics())

    @property
    def metrics(self) -> tuple[MetricDefinition, ...]:
        return self._metrics

    def __len__(self) -> int:
        return len(self._metrics)

    def get(self, metric_id: str) -> MetricDefinition | None:
        return self._by_id.get(metric_id.lower())

    def require(self, metric_id: str) -> MetricDefinition:
        metric = self.get(metric_id)
        if metric is None:
            raise KeyError(f"unknown metric: {metric_id}")
        return metric

    def resolve(self, term: str) -> MetricDefinition | None:
        normalized = _normalize(term)
        if not normalized:
            return None
        for metric in self._metrics:
            phrases = (metric.metric_id, metric.name, *metric.synonyms)
            if any(_normalize(phrase) == normalized for phrase in phrases):
                return metric
        for metric in self._metrics:
            phrases = sorted(
                (metric.metric_id, metric.name, *metric.synonyms),
                key=lambda item: len(_normalize(item)),
                reverse=True,
            )
            if any(_contains(normalized, _normalize(phrase)) for phrase in phrases):
                return metric
        return None

    def match_question(self, question: str) -> tuple[MetricDefinition, str] | None:
        normalized = _normalize(question)
        best: tuple[int, MetricDefinition, str] | None = None
        for metric in self._metrics:
            for phrase in (metric.metric_id, metric.name, *metric.synonyms):
                normalized_phrase = _normalize(phrase)
                if not _contains(normalized, normalized_phrase):
                    continue
                candidate = (len(normalized_phrase), metric, normalized_phrase)
                if best is None or candidate[0] > best[0]:
                    best = candidate
        if best is None:
            return None
        return best[1], best[2]


__all__ = ["MetricRegistry"]
