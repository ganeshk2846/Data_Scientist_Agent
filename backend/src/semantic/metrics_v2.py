"""Synthetic-layer KPIs (build plan Track 1; V2-SYN-4).

These are defined with the V1 ``MetricDefinition`` contract, unchanged, but
are kept out of ``MetricRegistry.default()`` so V1 routing and its tests see
exactly the nine governed metrics they always have. V2 code asks for
:func:`all_metrics` to get both.

Every metric here reads at least one synthetic table and is therefore
labelled synthetic wherever it is reported.
"""

from __future__ import annotations

from contracts.models import MetricAllowedDimension, MetricDefinition, MetricJoinPath

from catalog.registry import MetricRegistry

_APPROVED_AT = "2026-10-30T00:00:00Z"
_APPROVED_BY = "v2-synthetic-layer"
_SYNTHETIC_CAVEAT = (
    "Based on synthetic data generated for demonstration; not a measurement "
    "of the real business."
)

_ITEM_ORDERS = MetricJoinPath(edge_id="order_items.order_id=orders.order_id", cardinality="N:1")
_ITEM_PRODUCTS = MetricJoinPath(edge_id="order_items.product_id=products.product_id", cardinality="N:1")
_ITEM_PRICES = MetricJoinPath(edge_id="order_items.product_id=price_history.product_id", cardinality="N:M")
_ITEM_RETURNS = MetricJoinPath(
    edge_id="order_items.order_id,order_item_id=returns.order_id,order_item_id",
    cardinality="1:1",
)
_CUSTOMER_ORDERS = MetricJoinPath(edge_id="customers.customer_id=orders.customer_id", cardinality="1:N")
_TARGET_STATES = MetricJoinPath(
    edge_id="regional_targets.state=customers.customer_state", cardinality="1:N"
)


def _dim(name: str, column: str, table: str, *edges: str, synonyms: tuple[str, ...] = ()) -> MetricAllowedDimension:
    return MetricAllowedDimension(
        name=name, column=column, table=table, join_edges=edges, synonyms=synonyms
    )


_CATEGORY_SYNONYMS = ("category", "product category", "categories")
_STATE_SYNONYMS = ("state", "region", "customer state", "states")

SYNTHETIC_METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        metric_id="marketing_spend",
        name="Marketing Spend",
        synonyms=("marketing spend", "ad spend", "spend", "media spend", "advertising spend"),
        formula="SUM({{ marketing_spend }}.spend)",
        grain=("channel", "category", "day"),
        date_column="marketing_spend.date",
        allowed_dimensions=(
            _dim("channel", "channel", "marketing_spend", synonyms=("channel", "marketing channel")),
            _dim("product_category", "category", "marketing_spend", synonyms=_CATEGORY_SYNONYMS),
        ),
        base_table="marketing_spend",
        caveats=(_SYNTHETIC_CAVEAT,),
        approved_by=_APPROVED_BY,
        approved_at=_APPROVED_AT,
    ),
    MetricDefinition(
        metric_id="sessions",
        name="Web Sessions",
        synonyms=("sessions", "web sessions", "traffic", "visits", "site visits"),
        formula="SUM({{ web_traffic }}.sessions)",
        grain=("state", "day"),
        date_column="web_traffic.date",
        allowed_dimensions=(_dim("customer_state", "state", "web_traffic", synonyms=_STATE_SYNONYMS),),
        base_table="web_traffic",
        caveats=(_SYNTHETIC_CAVEAT,),
        approved_by=_APPROVED_BY,
        approved_at=_APPROVED_AT,
    ),
    MetricDefinition(
        metric_id="conversion_rate",
        name="Conversion Rate",
        synonyms=("conversion rate", "conversion", "cvr", "session conversion"),
        formula=(
            "SUM({{ web_traffic }}.sessions * {{ web_traffic }}.conversion_rate) "
            "/ NULLIF(SUM({{ web_traffic }}.sessions), 0)"
        ),
        grain=("state", "day"),
        date_column="web_traffic.date",
        allowed_dimensions=(_dim("customer_state", "state", "web_traffic", synonyms=_STATE_SYNONYMS),),
        base_table="web_traffic",
        caveats=(_SYNTHETIC_CAVEAT, "Session-weighted: converted sessions over sessions."),
        approved_by=_APPROVED_BY,
        approved_at=_APPROVED_AT,
    ),
    MetricDefinition(
        metric_id="stockout_rate",
        name="Stockout Rate",
        synonyms=("stockout rate", "stockouts", "out of stock rate", "stock-out rate"),
        formula=(
            "SUM({{ inventory_daily }}.stockout_flag) * 1.0 "
            "/ NULLIF(COUNT(*), 0)"
        ),
        grain=("category", "day"),
        date_column="inventory_daily.date",
        allowed_dimensions=(_dim("product_category", "category", "inventory_daily", synonyms=_CATEGORY_SYNONYMS),),
        base_table="inventory_daily",
        caveats=(_SYNTHETIC_CAVEAT, "Share of category-days flagged out of stock."),
        approved_by=_APPROVED_BY,
        approved_at=_APPROVED_AT,
    ),
    MetricDefinition(
        metric_id="return_rate",
        name="Return Rate",
        synonyms=("return rate", "returns rate", "refund rate"),
        formula=(
            "COUNT({{ returns }}.order_item_id) * 1.0 "
            "/ NULLIF(COUNT({{ order_items }}.order_item_id), 0)"
        ),
        required_filters=("{{ orders }}.order_status = 'delivered'",),
        grain=("order_item",),
        date_column="orders.order_purchase_timestamp",
        allowed_dimensions=(
            _dim("customer_state", "customer_state", "customers", _ITEM_ORDERS.edge_id, _CUSTOMER_ORDERS.edge_id, synonyms=_STATE_SYNONYMS),
            _dim("product_category", "product_category_name", "products", _ITEM_PRODUCTS.edge_id, synonyms=_CATEGORY_SYNONYMS),
        ),
        base_table="order_items",
        join_path=(_ITEM_RETURNS, _ITEM_ORDERS, _CUSTOMER_ORDERS, _ITEM_PRODUCTS),
        caveats=(_SYNTHETIC_CAVEAT, "Returned delivered items over delivered items, by purchase date."),
        approved_by=_APPROVED_BY,
        approved_at=_APPROVED_AT,
    ),
    MetricDefinition(
        metric_id="margin",
        name="Gross Margin",
        synonyms=("margin", "gross margin", "product margin", "margin rate"),
        formula=(
            "(SUM({{ order_items }}.price) - SUM({{ price_history }}.unit_cost)) "
            "/ NULLIF(SUM({{ order_items }}.price), 0)"
        ),
        required_filters=("{{ orders }}.order_status NOT IN ('canceled', 'unavailable')",),
        grain=("order_item",),
        date_column="orders.order_purchase_timestamp",
        allowed_dimensions=(
            _dim("product_category", "product_category_name", "products", _ITEM_PRODUCTS.edge_id, synonyms=_CATEGORY_SYNONYMS),
            _dim("customer_state", "customer_state", "customers", _ITEM_ORDERS.edge_id, _CUSTOMER_ORDERS.edge_id, synonyms=_STATE_SYNONYMS),
        ),
        base_table="order_items",
        join_path=(_ITEM_PRICES, _ITEM_ORDERS, _ITEM_PRODUCTS, _CUSTOMER_ORDERS),
        caveats=(
            _SYNTHETIC_CAVEAT,
            "Real item price less the synthetic unit cost from price_history (constant per product, so any one row per product serves the join).",
        ),
        approved_by=_APPROVED_BY,
        approved_at=_APPROVED_AT,
    ),
    MetricDefinition(
        metric_id="target_attainment",
        name="Revenue Target Attainment",
        synonyms=("target attainment", "attainment", "vs target", "against target", "revenue vs target"),
        formula=(
            "SUM({{ order_payments }}.payment_value) "
            "/ NULLIF(SUM({{ regional_targets }}.revenue_target), 0)"
        ),
        required_filters=("{{ orders }}.order_status NOT IN ('canceled', 'unavailable')",),
        grain=("state", "month"),
        date_column="regional_targets.month",
        allowed_dimensions=(_dim("customer_state", "state", "regional_targets", synonyms=_STATE_SYNONYMS),),
        base_table="regional_targets",
        join_path=(_TARGET_STATES, _CUSTOMER_ORDERS),
        caveats=(
            _SYNTHETIC_CAVEAT,
            "Real revenue over a synthetic target; monthly grain only.",
        ),
        approved_by=_APPROVED_BY,
        approved_at=_APPROVED_AT,
    ),
)

SYNTHETIC_METRIC_IDS = frozenset(metric.metric_id for metric in SYNTHETIC_METRICS)


def all_metrics() -> MetricRegistry:
    """The nine governed metrics plus the synthetic-layer KPIs."""
    return MetricRegistry((*MetricRegistry.default().metrics, *SYNTHETIC_METRICS))


def is_synthetic_metric(metric_id: str) -> bool:
    return metric_id in SYNTHETIC_METRIC_IDS


__all__ = ["SYNTHETIC_METRICS", "SYNTHETIC_METRIC_IDS", "all_metrics", "is_synthetic_metric"]
