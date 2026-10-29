import json
import sqlite3

from data_gen.generator import generate
from src.knowledge.metric_seeds import DEFAULT_SEEDS, seed_registry
from src.knowledge.stores import MetricRegistry


def test_demo_metric_seeds_are_complete_proposed_idempotent_and_reconcile(tmp_path):
    registry_path = tmp_path / "metrics.json"
    first = seed_registry(registry_path)
    second = seed_registry(registry_path)

    assert len(first) == len(second) == 3
    assert len(json.loads(registry_path.read_text(encoding="utf-8"))) == 3
    assert all(item["status"] == "proposed" for item in first)
    assert MetricRegistry(registry_path).approved() == []
    required = MetricRegistry.REQUIRED
    assert all(required <= item.keys() for item in first)

    warehouse = tmp_path / "seed-7.sqlite"
    generate(warehouse, table_count=50, seed=7)
    connection = sqlite3.connect(warehouse)
    try:
        metrics = {item["name"]: item for item in first}
        expected_orders = connection.execute(
            "SELECT COUNT(DISTINCT ord_key) FROM ord_hdr WHERE lower(trim(status)) <> 'cancelled' AND deleted_at IS NULL AND is_test=0"
        ).fetchone()[0]
        expected_revenue = connection.execute(
            "SELECT ROUND(SUM(amount),2) FROM ord_hdr WHERE lower(trim(status)) <> 'cancelled' AND deleted_at IS NULL AND is_test=0"
        ).fetchone()[0]
        expected_north = connection.execute(
            "SELECT revenue FROM monthly_kpi WHERE month='2024-06' AND region='North'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert metrics["demo_order_count"]["reconciliation_values"]["expected"] == expected_orders
    assert metrics["demo_order_revenue"]["reconciliation_values"]["expected_gbp"] == expected_revenue
    assert metrics["demo_monthly_region_revenue"]["reconciliation_values"]["2024-06 North"] == expected_north
