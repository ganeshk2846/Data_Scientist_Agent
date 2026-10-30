"""Table registry and data-layer computation (acceptance 1.4, 1.14; SY-1, SY-2)."""

from __future__ import annotations

import pytest
from contracts.v2 import ToolProvenance
from semantic.layers import (
    data_layer_for,
    data_layer_for_sql,
    synthetic_caveat,
    tables_in_sql,
)
from semantic.tables import TableRegistry

REAL = {
    "orders",
    "order_items",
    "order_payments",
    "order_reviews",
    "customers",
    "products",
    "sellers",
    "geolocation",
    "product_category_translation",
}
SYNTHETIC = {
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
}

ANALYTICAL = {
    "kpi_daily",
    "analytical_series",
    "analytical_anomalies",
    "analytical_forecasts",
    "driver_contributions",
}


def test_registry_holds_19_tables_with_synthetic_flag():
    registry = TableRegistry.default()

    assert len(registry.base()) == 19
    assert {t.name for t in registry.analytical()} == ANALYTICAL
    assert {t.name for t in registry.real()} == REAL
    assert {t.name for t in registry.synthetic()} == SYNTHETIC
    for table in registry.synthetic():
        assert table.source == "synthetic_generator"
        assert table.date_column is not None


def test_customer_segments_keys_on_the_person_not_the_order_customer():
    table = TableRegistry.default().require("customer_segments")
    assert table.key_columns == ("customer_unique_id",)


def test_tables_in_sql_ignores_ctes_and_aliases():
    sql = (
        "WITH m AS (SELECT o.order_id FROM orders o) "
        "SELECT * FROM m JOIN marketing_spend ms ON 1 = 1"
    )
    assert tables_in_sql(sql) == ("marketing_spend", "orders")


@pytest.mark.parametrize(
    ("tables", "layer", "synthetic"),
    [
        (["orders", "order_payments"], "real", ()),
        (["marketing_spend"], "synthetic", ("marketing_spend",)),
        (["Orders", "web_traffic", "promotions"], "mixed", ("promotions", "web_traffic")),
    ],
)
def test_data_layer_for(tables, layer, synthetic):
    assert data_layer_for(tables) == (layer, synthetic)


def test_analytical_tables_need_a_row_level_label():
    with pytest.raises(ValueError, match="per row"):
        data_layer_for(["analytical_anomalies"])
    assert data_layer_for(["analytical_anomalies"], analytical_rows_synthetic=False) == ("real", ())
    assert data_layer_for(
        ["orders", "analytical_anomalies"], analytical_rows_synthetic=True
    ) == ("mixed", ("analytical_anomalies",))


def test_unknown_table_fails_closed():
    with pytest.raises(KeyError, match="unregistered"):
        data_layer_for(["orders", "secret_salaries"])


def test_layer_from_sql_builds_a_valid_provenance():
    layer, synthetic = data_layer_for_sql(
        "SELECT channel, SUM(spend) FROM marketing_spend GROUP BY channel"
    )
    provenance = ToolProvenance(
        source="sql",
        query_ids=("q1",),
        data_layer=layer,
        synthetic_tables=synthetic,
    )
    assert provenance.data_layer == "synthetic"


def test_synthetic_caveat_names_every_table():
    caveat = synthetic_caveat(["web_traffic", "marketing_spend"])
    assert "synthetic" in caveat.lower()
    assert "marketing_spend, web_traffic are" in caveat
    assert synthetic_caveat([]) is None
