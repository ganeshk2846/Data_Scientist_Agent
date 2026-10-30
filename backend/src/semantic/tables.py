"""Registry of the warehouse tables V2 knows about, real and synthetic.

Every table carries ``is_synthetic`` so the label can never be lost between
the catalog and the answer (V2-SYN-4). The registry holds *descriptions and
structure* only; row counts and date spans are read from the database when
asked, so a discovery answer never reports a figure the catalog does not
hold (``SAFE-8``, acceptance 1.16).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from contracts.models import ContractModel
from pydantic import Field

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
    "analytics",
    "user_data",
]

TableSource = Literal["olist_snapshot", "synthetic_generator", "user_supplied", "analytical"]

#: The calendar window the synthetic generator writes (V2-SYN-3): the real
#: snapshot's months, 2016-09 to 2018-10, so every synthetic date can be
#: joined to a real one.
SYNTHETIC_WINDOW = ("2016-09-01", "2018-10-31")


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


def _analytical(name, description, keys) -> TableInfo:
    # Derived engine/SQL output. The table itself is not synthetic, but each
    # row carries ``is_synthetic`` for the KPI it holds (AT-5): readers must
    # label per row, never per table.
    return TableInfo(
        name=name,
        subject="analytics",
        grain="see description",
        description=description,
        key_columns=keys,
        source="analytical",
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
    _synthetic("marketing_spend", "marketing", "channel x category x day", "Daily paid spend per marketing channel and product category (BRL).", ("date", "channel", "category"), "date"),
    _synthetic("promotions", "marketing", "promotion x category", "Discount promotions per category, with start and end dates.", ("promo_id", "category"), "start_date"),
    _synthetic("inventory_daily", "operations", "category x day", "Stock on hand, units sold and stockout flag per category.", ("date", "category"), "date"),
    _synthetic("web_traffic", "marketing", "state x day", "Sessions, conversion rate and boleto checkout share per customer state.", ("date", "state"), "date"),
    _synthetic("price_history", "pricing", "product x price change", "List price and unit cost per product, one row per price change.", ("product_id", "date"), "date"),
    _synthetic("competitor_prices", "pricing", "product x competitor x week", "Weekly observed competitor price for the top-selling products.", ("product_id", "date", "competitor"), "date"),
    _synthetic("customer_segments", "customers", "customer", "Segment, LTV band and acquisition channel per customer_unique_id.", ("customer_unique_id",), "assigned_at"),
    _synthetic("regional_targets", "targets", "state x month", "Monthly revenue target per customer state (BRL).", ("state", "month"), "month"),
    _synthetic("returns", "operations", "order item", "Returned order items with reason and refund value.", ("order_id", "order_item_id"), "return_date"),
    _synthetic("delivery_sla", "operations", "carrier x state x day", "Promised vs actual delivery days, SLA breach flag and freight cost per carrier and state.", ("date", "carrier", "state"), "date"),
    _analytical("kpi_daily", "Daily value of every governed and synthetic KPI, with numerator and denominator.", ("kpi", "date")),
    _analytical("analytical_series", "Monthly KPI series, total and by each governed dimension.", ("kpi", "period", "dimension", "dimension_value")),
    _analytical("analytical_anomalies", "python.anomaly output for every tested month and series.", ("kpi", "date", "dimension", "dimension_value")),
    _analytical("analytical_forecasts", "python.forecast output anchored on the last complete month.", ("kpi", "dimension", "dimension_value", "date")),
    _analytical("driver_contributions", "python.driver month-over-month contributions by dimension.", ("kpi", "dimension", "dimension_value", "current_period")),
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
        return tuple(
            table
            for table in self.tables
            if table.source in ("olist_snapshot", "user_supplied")
        )

    def base(self) -> tuple[TableInfo, ...]:
        """The warehouse tables, excluding derived analytical tables."""
        return tuple(table for table in self.tables if table.source != "analytical")

    def analytical(self) -> tuple[TableInfo, ...]:
        return tuple(table for table in self.tables if table.source == "analytical")

    def with_tables(self, extra: Iterable[TableInfo]) -> TableRegistry:
        """A new registry with ``extra`` (e.g. ingested tables) appended."""
        return TableRegistry((*self.tables, *extra))

    def with_ingested(self, registry_path: Path) -> TableRegistry:
        """Add the tables ``scripts/ingest.py`` registered, if any."""
        return self.with_tables(load_ingested(registry_path))


def load_ingested(registry_path: Path) -> tuple[TableInfo, ...]:
    """Tables registered by ``scripts/ingest.py`` (``source = user_supplied``)."""
    path = Path(registry_path)
    if not path.is_file():
        return ()
    return ingested_tables(json.loads(path.read_text(encoding="utf-8")))


def ingested_tables(payload: dict) -> tuple[TableInfo, ...]:
    """TableInfo entries from an ingestion registry payload."""
    return tuple(
        TableInfo(
            name=entry["name"],
            subject="user_data",
            grain=entry["grain"],
            description=entry["description"],
            key_columns=tuple(entry["key_columns"]),
            date_column=entry.get("date_column"),
            source="user_supplied",
        )
        for entry in payload.get("tables", ())
    )


__all__ = ["SYNTHETIC_WINDOW", "TableInfo", "TableRegistry", "TableSource", "ingested_tables", "load_ingested"]
