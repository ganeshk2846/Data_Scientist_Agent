"""Table registry and metadata for real, synthetic, and analytical layers (V2-SYN-4)."""

from __future__ import annotations

from dataclasses import dataclass

REAL_TABLE_NAMES = frozenset(
    [
        "customers",
        "geolocation",
        "order_items",
        "order_payments",
        "order_reviews",
        "orders",
        "product_category_translation",
        "products",
        "sellers",
    ]
)

SYNTHETIC_TABLE_NAMES = frozenset(
    [
        "marketing_spend",
        "promotions",
        "inventory_daily",
        "web_traffic",
        "price_history",
        "competitor_prices",
        "customer_segments",
        "regional_targets",
        "returns",
        "delivery_sla",
    ]
)

ANALYTICAL_TABLE_NAMES = frozenset(
    [
        "analytical_series",
        "kpi_daily",
        "analytical_anomalies",
        "analytical_forecasts",
        "driver_contributions",
    ]
)


@dataclass(frozen=True)
class TableMetadata:
    name: str
    grain: str
    is_synthetic: bool
    is_analytical: bool
    primary_key: tuple[str, ...]
    description: str


TABLES: dict[str, TableMetadata] = {
    # 9 Real Tables
    "orders": TableMetadata(
        name="orders",
        grain="order",
        is_synthetic=False,
        is_analytical=False,
        primary_key=("order_id",),
        description="Core orders table capturing order lifecycle status and timestamps.",
    ),
    "order_items": TableMetadata(
        name="order_items",
        grain="order_item",
        is_synthetic=False,
        is_analytical=False,
        primary_key=("order_id", "order_item_id"),
        description="Line-item order details with prices, freight, product IDs, and seller IDs.",
    ),
    "customers": TableMetadata(
        name="customers",
        grain="customer_order_instance",
        is_synthetic=False,
        is_analytical=False,
        primary_key=("customer_id",),
        description="Customer records linking customer_id (order instance) to customer_unique_id.",
    ),
    "products": TableMetadata(
        name="products",
        grain="product",
        is_synthetic=False,
        is_analytical=False,
        primary_key=("product_id",),
        description="Product catalog details including category, weight, and dimensions.",
    ),
    "sellers": TableMetadata(
        name="sellers",
        grain="seller",
        is_synthetic=False,
        is_analytical=False,
        primary_key=("seller_id",),
        description="Merchant seller profiles with location and zip code.",
    ),
    "order_payments": TableMetadata(
        name="order_payments",
        grain="payment_installment",
        is_synthetic=False,
        is_analytical=False,
        primary_key=("order_id", "payment_sequential"),
        description="Payment tender methods, installment schedules, and payment values.",
    ),
    "order_reviews": TableMetadata(
        name="order_reviews",
        grain="review",
        is_synthetic=False,
        is_analytical=False,
        primary_key=("review_id",),
        description="Customer satisfaction review scores (1-5) and feedback timestamps.",
    ),
    "geolocation": TableMetadata(
        name="geolocation",
        grain="zip_prefix",
        is_synthetic=False,
        is_analytical=False,
        primary_key=("geolocation_zip_code_prefix",),
        description="Brazilian zip code prefixes with latitude and longitude coordinates.",
    ),
    "product_category_translation": TableMetadata(
        name="product_category_translation",
        grain="category",
        is_synthetic=False,
        is_analytical=False,
        primary_key=("product_category_name",),
        description="Portuguese to English translation map for 71 product categories.",
    ),
    # 10 Synthetic Tables
    "marketing_spend": TableMetadata(
        name="marketing_spend",
        grain="channel_day_state",
        is_synthetic=True,
        is_analytical=False,
        primary_key=("date", "channel", "customer_state"),
        description="Synthetic marketing investment: daily spend, clicks, and impressions by channel and state.",
    ),
    "promotions": TableMetadata(
        name="promotions",
        grain="promotion",
        is_synthetic=True,
        is_analytical=False,
        primary_key=("promo_id",),
        description="Synthetic promotional campaigns, discount percentages, and category targets.",
    ),
    "inventory_daily": TableMetadata(
        name="inventory_daily",
        grain="product_day",
        is_synthetic=True,
        is_analytical=False,
        primary_key=("date", "product_id"),
        description="Synthetic daily inventory levels, units on hand, units sold, and stockout flags.",
    ),
    "web_traffic": TableMetadata(
        name="web_traffic",
        grain="channel_day_state",
        is_synthetic=True,
        is_analytical=False,
        primary_key=("date", "channel", "customer_state"),
        description="Synthetic e-commerce web traffic: sessions, bounce rate, carts, and checkout starts.",
    ),
    "price_history": TableMetadata(
        name="price_history",
        grain="product_day",
        is_synthetic=True,
        is_analytical=False,
        primary_key=("product_id", "date"),
        description="Synthetic price records over time tracking list price vs effective price.",
    ),
    "competitor_prices": TableMetadata(
        name="competitor_prices",
        grain="product_day",
        is_synthetic=True,
        is_analytical=False,
        primary_key=("date", "product_id"),
        description="Synthetic competitor pricing intelligence across benchmark merchants.",
    ),
    "customer_segments": TableMetadata(
        name="customer_segments",
        grain="customer_unique_id",
        is_synthetic=True,
        is_analytical=False,
        primary_key=("customer_unique_id",),
        description="Synthetic customer segmentation: RFM clusters, LTV tier, and acquisition channels.",
    ),
    "regional_targets": TableMetadata(
        name="regional_targets",
        grain="state_month_metric",
        is_synthetic=True,
        is_analytical=False,
        primary_key=("month", "customer_state", "metric_id"),
        description="Synthetic monthly business targets for revenue and order count by state.",
    ),
    "returns": TableMetadata(
        name="returns",
        grain="order_item",
        is_synthetic=True,
        is_analytical=False,
        primary_key=("order_id", "order_item_id"),
        description="Synthetic customer merchandise returns: return dates, reasons, and refund amounts.",
    ),
    "delivery_sla": TableMetadata(
        name="delivery_sla",
        grain="carrier_day_state",
        is_synthetic=True,
        is_analytical=False,
        primary_key=("date", "carrier", "customer_state"),
        description="Synthetic logistics SLA performance: carrier transit days and breach flags.",
    ),
    # Precomputed Analytical Tables
    "analytical_series": TableMetadata(
        name="analytical_series",
        grain="metric_grain_dimension",
        is_synthetic=False,
        is_analytical=True,
        primary_key=("kpi", "date", "dimension", "dimension_value"),
        description="Precomputed metric series aggregates by governed dimensions.",
    ),
    "analytical_anomalies": TableMetadata(
        name="analytical_anomalies",
        grain="kpi_date_dimension",
        is_synthetic=False,
        is_analytical=True,
        primary_key=("kpi", "date", "dimension", "dimension_value"),
        description="Precomputed anomaly scores and flags enabling single-read lookup for S5.",
    ),
    "analytical_forecasts": TableMetadata(
        name="analytical_forecasts",
        grain="kpi_ds_dimension",
        is_synthetic=False,
        is_analytical=True,
        primary_key=("kpi", "ds", "dimension", "dimension_value"),
        description="Precomputed statistical forecasts with prediction intervals anchored on 2018-08.",
    ),
    "driver_contributions": TableMetadata(
        name="driver_contributions",
        grain="metric_dimension_periods",
        is_synthetic=False,
        is_analytical=True,
        primary_key=(
            "metric",
            "dimension",
            "current_period",
            "comparison_period",
            "dimension_value",
        ),
        description="Precomputed period-over-period contribution waterfalls.",
    ),
}


def is_table_synthetic(table_name: str) -> bool:
    """Return True if the table belongs to the synthetic data layer (V2-SYN-4)."""
    table_clean = table_name.lower().strip()
    return table_clean in SYNTHETIC_TABLE_NAMES


def table_registry() -> dict[str, TableMetadata]:
    """Return dictionary of all registered table metadata."""
    return dict(TABLES)
