"""Per-period SQL for every KPI, for the precomputed analytical tables.

Each :class:`KpiSpec` is a fixed SQL shape - source, filter, date, numerator,
denominator, dimensions - so a KPI's value for any period and dimension
value is ``numerator / denominator`` (or ``numerator`` when additive), read
straight from the warehouse. Python never aggregates rows into a figure; it
only divides the two SQL sums for ratio and mean metrics (SAFE-8).

Storing numerator and denominator beside the value means a ratio can be
re-aggregated correctly later (``semantic.aggregation``), instead of
averaging averages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from semantic.aggregation import AggregationRegistry
from semantic.metrics_v2 import SYNTHETIC_METRIC_IDS

Grain = Literal["day", "month"]

_COMPLETED = "o.order_status NOT IN ('canceled', 'unavailable')"
_ORDERS = "orders.order_purchase_timestamp"
_PAYMENTS = (
    "order_payments op JOIN orders o ON o.order_id = op.order_id "
    "JOIN customers c ON c.customer_id = o.customer_id"
)
_ITEMS = (
    "order_items oi JOIN orders o ON o.order_id = oi.order_id "
    "JOIN customers c ON c.customer_id = o.customer_id "
    "LEFT JOIN products p ON p.product_id = oi.product_id"
)
_ORDERS_CUSTOMERS = "orders o JOIN customers c ON c.customer_id = o.customer_id"
_STATE = {"customer_state": "c.customer_state"}
_CATEGORY = {"product_category": "COALESCE(p.product_category_name, 'unknown')"}


@dataclass(frozen=True)
class KpiSpec:
    kpi: str
    source: str
    date_expr: str
    numerator: str
    denominator: str | None = None
    where: str | None = None
    dimensions: dict[str, str] = field(default_factory=dict)
    grains: tuple[Grain, ...] = ("day", "month")
    completeness_columns: tuple[str, ...] = (_ORDERS,)

    @property
    def is_synthetic(self) -> bool:
        return self.kpi in SYNTHETIC_METRIC_IDS

    def sql(self, grain: Grain, dimension: str | None = None) -> str:
        if grain not in self.grains:
            raise ValueError(f"{self.kpi} is not available at the {grain} grain")
        width = 10 if grain == "day" else 7
        period = f"substr({self.date_expr}, 1, {width})"
        select = [f"{period} AS period"]
        group = ["period"]
        if dimension is not None:
            select.append(f"{self.dimensions[dimension]} AS dimension_value")
            group.append("dimension_value")
        select.append(f"{self.numerator} AS numerator")
        select.append(f"{self.denominator or 'NULL'} AS denominator")
        where = f" WHERE {self.where}" if self.where else ""
        return (
            f"SELECT {', '.join(select)} FROM {self.source}{where} "
            f"GROUP BY {', '.join(group)} ORDER BY {', '.join(group)}"
        )


KPI_SPECS: tuple[KpiSpec, ...] = (
    KpiSpec("revenue", _PAYMENTS, "o.order_purchase_timestamp", "SUM(op.payment_value)",
            where=_COMPLETED, dimensions={**_STATE, "payment_type": "op.payment_type"}),
    KpiSpec("gmv", _ITEMS, "o.order_purchase_timestamp", "SUM(oi.price + oi.freight_value)",
            where=_COMPLETED, dimensions={**_STATE, **_CATEGORY}),
    KpiSpec("order_count", _ORDERS_CUSTOMERS, "o.order_purchase_timestamp", "COUNT(DISTINCT o.order_id)",
            dimensions={**_STATE, "order_status": "o.order_status"}),
    KpiSpec("aov", _PAYMENTS, "o.order_purchase_timestamp", "SUM(op.payment_value)",
            denominator="COUNT(DISTINCT o.order_id)", where=_COMPLETED,
            dimensions={**_STATE, "payment_type": "op.payment_type"}),
    KpiSpec("review_score",
            "order_reviews r JOIN orders o ON o.order_id = r.order_id JOIN customers c ON c.customer_id = o.customer_id",
            "o.order_purchase_timestamp", "SUM(r.review_score)", denominator="COUNT(r.review_score)",
            dimensions=_STATE),
    KpiSpec("freight_value", _ITEMS, "o.order_purchase_timestamp", "SUM(oi.freight_value)",
            where=_COMPLETED, dimensions={**_STATE, **_CATEGORY}),
    KpiSpec("item_count", _ITEMS, "o.order_purchase_timestamp", "COUNT(oi.order_item_id)",
            where=_COMPLETED, dimensions={**_STATE, **_CATEGORY}),
    KpiSpec("customer_count", _ORDERS_CUSTOMERS, "o.order_purchase_timestamp",
            "COUNT(DISTINCT c.customer_unique_id)", dimensions=_STATE),
    KpiSpec("cancellation_rate", _ORDERS_CUSTOMERS, "o.order_purchase_timestamp",
            "SUM(CASE WHEN o.order_status = 'canceled' THEN 1.0 ELSE 0.0 END)",
            denominator="COUNT(o.order_id)", dimensions=_STATE),
    # Synthetic-layer KPIs.
    KpiSpec("marketing_spend", "marketing_spend ms", "ms.date", "SUM(ms.spend)",
            dimensions={"channel": "ms.channel", "product_category": "ms.category"},
            completeness_columns=("marketing_spend.date",)),
    KpiSpec("sessions", "web_traffic wt", "wt.date", "SUM(wt.sessions)",
            dimensions={"customer_state": "wt.state"}, completeness_columns=("web_traffic.date",)),
    KpiSpec("conversion_rate", "web_traffic wt", "wt.date", "SUM(wt.sessions * wt.conversion_rate)",
            denominator="SUM(wt.sessions)", dimensions={"customer_state": "wt.state"},
            completeness_columns=("web_traffic.date",)),
    KpiSpec("stockout_rate", "inventory_daily inv", "inv.date", "SUM(inv.stockout_flag)",
            denominator="COUNT(*)", dimensions={"product_category": "inv.category"},
            completeness_columns=("inventory_daily.date",)),
    KpiSpec("return_rate",
            _ITEMS + " LEFT JOIN returns rt ON rt.order_id = oi.order_id AND rt.order_item_id = oi.order_item_id",
            "o.order_purchase_timestamp", "COUNT(rt.order_item_id)", denominator="COUNT(oi.order_item_id)",
            where="o.order_status = 'delivered'", dimensions={**_STATE, **_CATEGORY}),
    KpiSpec("margin",
            _ITEMS + " JOIN (SELECT product_id, MIN(unit_cost) AS unit_cost FROM price_history GROUP BY product_id) pc"
            " ON pc.product_id = oi.product_id",
            "o.order_purchase_timestamp", "SUM(oi.price) - SUM(pc.unit_cost)", denominator="SUM(oi.price)",
            where=_COMPLETED, dimensions={**_STATE, **_CATEGORY}),
    KpiSpec("target_attainment",
            "regional_targets tg LEFT JOIN (SELECT c.customer_state AS state, "
            "substr(o.order_purchase_timestamp, 1, 7) AS month, SUM(op.payment_value) AS revenue "
            f"FROM {_PAYMENTS} WHERE {_COMPLETED} GROUP BY state, month) rv "
            "ON rv.state = tg.state AND rv.month = tg.month",
            "tg.month", "SUM(COALESCE(rv.revenue, 0))", denominator="SUM(tg.revenue_target)",
            dimensions={"customer_state": "tg.state"}, grains=("month",),
            completeness_columns=("regional_targets.month", _ORDERS)),
)

_BY_KPI = {spec.kpi: spec for spec in KPI_SPECS}


def kpi_spec(kpi: str) -> KpiSpec:
    try:
        return _BY_KPI[kpi]
    except KeyError:
        raise KeyError(f"no SQL spec for KPI {kpi!r}") from None


def _consistent() -> None:
    aggregations = AggregationRegistry()
    for spec in KPI_SPECS:
        additive = aggregations.require(spec.kpi).is_additive
        if additive == (spec.denominator is not None):
            raise AssertionError(f"{spec.kpi}: denominator does not match its aggregation class")


_consistent()

__all__ = ["KPI_SPECS", "KpiSpec", "kpi_spec"]
