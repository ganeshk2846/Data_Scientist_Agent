"""Registry of the warehouse tables V2 knows about, real and synthetic.

Every table carries ``is_synthetic`` so the label can never be lost between
the catalog and the answer (V2-SYN-4). The registry holds *descriptions and
structure* only; row counts and date spans are read from the database when
asked, so a discovery answer never reports a figure the catalog does not
hold (``SAFE-8``, acceptance 1.16).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field

from contracts.models import ContractModel

Subject = Literal[
    "orders",
    "customers",
    "products",
    "sellers",
    "geography",
    "marketing",
    "pricing",
    "operations",
    "targets",
]

TableSource = Literal["olist_snapshot", "synthetic_generator", "user_supplied"]

#: The window the synthetic generator writes, complete periods only (V2-SYN-3).
SYNTHETIC_WINDOW = ("2016-10", "2018-08")


class TableInfo(ContractModel):
    name: str = Field(pattern=r"^[a-z_][a-z0-9_]*$")
    subject: Subject
    grain: str = Field(min_length=1)
    description: str = Field(min_length=1)
    key_columns: tuple[str, ...] = Field(min_length=1)
    date_column: str | None = None
    is_synthetic: bool = False
    source: TableSource = "olist_snapshot"


def _real(name, subject, grain, description, keys, date_column=None) -> TableInfo:
    return TableInfo(
        name=name,
        subject=subject,
        grain=grain,
        description=description,
        key_columns=keys,
        date_column=date_column,
    )


def _synthetic(name, subject, grain, description, keys, date_column) -> TableInfo:
    return TableInfo(
        name=name,
        subject=subject,
        grain=grain,
        description=description,
        key_columns=keys,
        date_column=date_column,
        is_synthetic=True,
        source="synthetic_generator",
    )


_TABLES: tuple[TableInfo, ...] = (
    _real("orders", "orders", "order", "One row per order with its status and lifecycle timestamps.", ("order_id",), "order_purchase_timestamp"),
    _real("order_items", "orders", "order item", "One row per item in an order, with price and freight.", ("order_id", "order_item_id")),
    _real("order_payments", "orders", "payment", "One row per payment instalment of an order.", ("order_id", "payment_sequential")),
    _real("order_reviews", "orders", "review", "Customer review score and comment for an order.", ("review_id",), "review_creation_date"),
    _real("customers", "customers", "customer per order", "One row per order-customer; customer_unique_id is the person.", ("customer_id",)),
    _real("products", "products", "product", "Product attributes and Portuguese category name.", ("product_id",)),
    _real("sellers", "sellers", "seller", "Seller location.", ("seller_id",)),
    _real("geolocation", "geography", "zip prefix point", "Latitude and longitude per zip code prefix.", ("geolocation_zip_code_prefix",)),
    _real("product_category_translation", "products", "category", "Portuguese to English category names.", ("product_category_name",)),
    _synthetic("marketing_spend", "marketing", "channel x state x day", "Daily paid spend, impressions and clicks per channel and state.", ("date", "channel", "customer_state"), "date"),
    _synthetic("promotions", "marketing", "promo x category x day", "Discount promotions per category and channel.", ("promo_id", "date", "product_category"), "date"),
    _synthetic("inventory_daily", "operations", "product x day", "Units on hand, units sold and stockout flag per product.", ("date", "product_id"), "date"),
    _synthetic("web_traffic", "marketing", "channel x day", "Sessions, bounce rate and funnel steps per channel.", ("date", "channel"), "date"),
    _synthetic("price_history", "pricing", "product x day", "List and effective price per product.", ("date", "product_id"), "date"),
    _synthetic("competitor_prices", "pricing", "product x competitor x day", "Observed competitor price per product.", ("date", "product_id", "competitor_name"), "date"),
    _synthetic("customer_segments", "customers", "customer", "Segment, LTV band and acquisition channel per customer_unique_id.", ("customer_unique_id",), "assigned_at"),
    _synthetic("regional_targets", "targets", "state x month x metric", "Monthly target per state and governed metric.", ("month", "customer_state", "metric_id"), "month"),
    _synthetic("returns", "operations", "order item", "Returned order items with reason and refund.", ("order_id", "order_item_id"), "return_date"),
    _synthetic("delivery_sla", "operations", "carrier x state x day", "Promised vs actual delivery days and SLA breach flag.", ("date", "carrier", "customer_state"), "date"),
)


class TableRegistry:
    """Closed lookup of known tables; unknown names fail closed."""

    def __init__(self, tables: Iterable[TableInfo] = _TABLES) -> None:
        by_name: dict[str, TableInfo] = {}
        for table in tables:
            if table.name in by_name:
                raise ValueError(f"duplicate table {table.name!r}")
            by_name[table.name] = table
        self._by_name = by_name

    @classmethod
    def default(cls) -> TableRegistry:
        return cls()

    def __len__(self) -> int:
        return len(self._by_name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name.lower() in self._by_name

    @property
    def tables(self) -> tuple[TableInfo, ...]:
        return tuple(self._by_name.values())

    def get(self, name: str) -> TableInfo | None:
        return self._by_name.get(name.lower())

    def require(self, name: str) -> TableInfo:
        table = self.get(name)
        if table is None:
            raise KeyError(f"table {name!r} is not registered")
        return table

    def synthetic(self) -> tuple[TableInfo, ...]:
        return tuple(table for table in self.tables if table.is_synthetic)

    def real(self) -> tuple[TableInfo, ...]:
        return tuple(table for table in self.tables if not table.is_synthetic)


__all__ = ["SYNTHETIC_WINDOW", "TableInfo", "TableRegistry", "TableSource"]
