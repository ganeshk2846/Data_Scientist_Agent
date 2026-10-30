"""Real Olist keys and shapes the synthetic tables are keyed to (V2-SYN-3).

Everything is read once, through a read-only connection, into pandas frames.
The generator never writes to the source; this module never even holds a
writable handle to it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REAL_TABLES = (
    "customers",
    "geolocation",
    "order_items",
    "order_payments",
    "order_reviews",
    "orders",
    "product_category_translation",
    "products",
    "sellers",
)

#: Calendar window of every synthetic date: the real snapshot's months.
WINDOW_START = pd.Timestamp("2016-09-01")
WINDOW_END = pd.Timestamp("2018-10-31")

#: Months whose real order volume is complete (V2-DATA-1). Used only to pick
#: baselines for targets; never written into a synthetic row.
COMPLETE_MONTHS = pd.period_range("2017-01", "2018-08", freq="M")

_COMPLETED = "o.order_status NOT IN ('canceled', 'unavailable')"


def open_read_only(path: Path) -> sqlite3.Connection:
    """Open ``path`` read-only; a write through this handle raises."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"source database not found: {path}")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


@dataclass(frozen=True)
class SourceContext:
    states: pd.DataFrame        # customer_state, orders, share
    categories: pd.DataFrame    # category, items, gmv, share, gmv_share
    products: pd.DataFrame      # product_id, category, base_price, items
    items: pd.DataFrame         # order_id, order_item_id, price, status, purchase, delivered, state
    customers: pd.DataFrame     # customer_unique_id, orders, total, first_purchase, last_purchase
    state_month_revenue: pd.DataFrame  # state, month, revenue

    @property
    def state_codes(self) -> list[str]:
        return list(self.states["customer_state"])

    @property
    def category_names(self) -> list[str]:
        return list(self.categories["category"])


def _missing_tables(conn: sqlite3.Connection) -> list[str]:
    present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return [name for name in REAL_TABLES if name not in present]


def load_context(conn: sqlite3.Connection) -> SourceContext:
    missing = _missing_tables(conn)
    if missing:
        raise ValueError(f"source is not an Olist snapshot; missing tables: {', '.join(missing)}")

    states = pd.read_sql_query(
        "SELECT c.customer_state, COUNT(DISTINCT o.order_id) AS orders "
        "FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
        "GROUP BY c.customer_state ORDER BY c.customer_state",
        conn,
    )
    states["share"] = states["orders"] / states["orders"].sum()

    categories = pd.read_sql_query(
        "SELECT p.product_category_name AS category, COUNT(*) AS items, "
        "SUM(oi.price) AS gmv FROM order_items oi "
        "JOIN products p ON p.product_id = oi.product_id "
        "WHERE p.product_category_name IS NOT NULL "
        "GROUP BY p.product_category_name ORDER BY p.product_category_name",
        conn,
    )
    categories["share"] = categories["items"] / categories["items"].sum()
    categories["gmv_share"] = categories["gmv"] / categories["gmv"].sum()

    products = pd.read_sql_query(
        "SELECT p.product_id, p.product_category_name AS category, "
        "AVG(oi.price) AS base_price, COUNT(oi.order_id) AS items "
        "FROM products p LEFT JOIN order_items oi ON oi.product_id = p.product_id "
        "GROUP BY p.product_id ORDER BY p.product_id",
        conn,
    )
    fallback = float(products["base_price"].median()) if products["base_price"].notna().any() else 100.0
    products["base_price"] = products["base_price"].fillna(fallback)

    items = pd.read_sql_query(
        "SELECT oi.order_id, oi.order_item_id, oi.price, o.order_status AS status, "
        "o.order_purchase_timestamp AS purchase, o.order_delivered_customer_date AS delivered, "
        "c.customer_state AS state FROM order_items oi "
        "JOIN orders o ON o.order_id = oi.order_id "
        "JOIN customers c ON c.customer_id = o.customer_id "
        "ORDER BY oi.order_id, oi.order_item_id",
        conn,
    )
    items["purchase"] = pd.to_datetime(items["purchase"])
    items["delivered"] = pd.to_datetime(items["delivered"])

    customers = pd.read_sql_query(
        "SELECT c.customer_unique_id, COUNT(DISTINCT o.order_id) AS orders, "
        "COALESCE(SUM(op.payment_value), 0) AS total, "
        "MIN(o.order_purchase_timestamp) AS first_purchase, "
        "MAX(o.order_purchase_timestamp) AS last_purchase "
        "FROM customers c JOIN orders o ON o.customer_id = c.customer_id "
        "LEFT JOIN order_payments op ON op.order_id = o.order_id "
        "GROUP BY c.customer_unique_id ORDER BY c.customer_unique_id",
        conn,
    )
    customers["first_purchase"] = pd.to_datetime(customers["first_purchase"])
    customers["last_purchase"] = pd.to_datetime(customers["last_purchase"])

    state_month_revenue = pd.read_sql_query(
        "SELECT c.customer_state AS state, strftime('%Y-%m', o.order_purchase_timestamp) AS month, "
        "SUM(op.payment_value) AS revenue FROM orders o "
        "JOIN customers c ON c.customer_id = o.customer_id "
        "JOIN order_payments op ON op.order_id = o.order_id "
        f"WHERE {_COMPLETED} GROUP BY state, month ORDER BY state, month",
        conn,
    )
    return SourceContext(
        states=states,
        categories=categories,
        products=products,
        items=items,
        customers=customers,
        state_month_revenue=state_month_revenue,
    )


__all__ = [
    "COMPLETE_MONTHS",
    "REAL_TABLES",
    "SourceContext",
    "WINDOW_END",
    "WINDOW_START",
    "load_context",
    "open_read_only",
]
