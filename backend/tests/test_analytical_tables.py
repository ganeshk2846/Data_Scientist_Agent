"""Precomputed analytical tables (acceptance 1.10-1.12; AT-1..5; S5)."""

from __future__ import annotations

import sqlite3

import pytest

from contracts.v2 import AnomalyRow, ForecastRow
from scripts.build_analytical_tables import build
from semantic.kpis import KPI_SPECS
from semantic.metrics_v2 import SYNTHETIC_METRIC_IDS
from semantic.versioning import catalog_version

REAL_KPIS = {spec.kpi for spec in KPI_SPECS} - SYNTHETIC_METRIC_IDS


def _q(db, sql, *params):
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def test_all_five_tables_are_built(v2_build):
    counts = v2_build["analytical_counts"]
    assert set(counts) == {"kpi_daily", "analytical_series", "analytical_anomalies", "analytical_forecasts", "driver_contributions"}
    assert all(count > 0 for count in counts.values())


def test_every_kpi_has_a_monthly_series_and_daily_where_defined(v2_build):
    monthly = {row["kpi"] for row in _q(v2_build["db"], "SELECT DISTINCT kpi FROM analytical_series")}
    daily = {row["kpi"] for row in _q(v2_build["db"], "SELECT DISTINCT kpi FROM kpi_daily")}
    assert monthly == {spec.kpi for spec in KPI_SPECS}
    assert daily == {spec.kpi for spec in KPI_SPECS if "day" in spec.grains}


def test_series_matches_an_independent_query(v2_build):
    (row,) = _q(v2_build["db"], "SELECT value FROM analytical_series WHERE kpi = 'revenue' AND period = '2018-03' AND dimension IS NULL")
    (direct,) = _q(v2_build["db"], """
        SELECT SUM(op.payment_value) AS v FROM order_payments op JOIN orders o ON o.order_id = op.order_id
        WHERE o.order_status NOT IN ('canceled', 'unavailable') AND o.order_purchase_timestamp LIKE '2018-03%'""")
    assert row["value"] == pytest.approx(direct["v"])


def test_ratio_rows_keep_numerator_and_denominator(v2_build):
    rows = _q(v2_build["db"], "SELECT value, numerator, denominator FROM analytical_series WHERE kpi = 'aov' AND dimension IS NULL")
    assert rows
    for row in rows:
        assert row["value"] == pytest.approx(row["numerator"] / row["denominator"])


def test_incomplete_months_are_flagged_in_the_series(v2_build):
    rows = {r["period"]: r["complete"] for r in _q(v2_build["db"], "SELECT period, complete FROM analytical_series WHERE kpi = 'revenue' AND dimension IS NULL")}
    assert rows["2018-08"] == 1
    assert rows.get("2018-09", 0) == 0 and rows.get("2016-09", 0) == 0


def test_forecasts_anchor_on_the_last_complete_month(v2_build):
    rows = _q(v2_build["db"], "SELECT * FROM analytical_forecasts")
    for row in rows:
        payload = {key: value for key, value in row.items() if key != "date"}
        ForecastRow.model_validate({**payload, "ds": row["date"], "is_synthetic": bool(row["is_synthetic"])})
    anchors = {(r["kpi"], r["anchor_period"]) for r in rows}
    for kpi in REAL_KPIS:
        assert (kpi, "2018-08") in anchors, kpi
    assert {r["model"] for r in rows} == {"ets"}  # Prophet is not installed here
    assert all(r["model_fallback_reason"] for r in rows)


def test_mape_is_real_or_null_never_zero(v2_build):
    mapes = [r["mape"] for r in _q(v2_build["db"], "SELECT mape FROM analytical_forecasts")]
    assert all(m is None or m > 0 for m in mapes)


def test_s5_spikes_across_all_months_is_one_read(v2_build):
    """'What are the spikes across all months?' - one indexed read, ranked by score."""
    rows = _q(v2_build["db"], """
        SELECT kpi, date, dimension, direction, score, engine_version, is_synthetic
        FROM analytical_anomalies WHERE flagged = 1 ORDER BY ABS(score) DESC LIMIT 20""")
    found = {(r["kpi"], r["date"]) for r in rows if r["dimension"] is None}
    assert ("stockout_rate", "2017-11-01") in found  # E2
    assert ("conversion_rate", "2018-01-01") in found  # E3
    assert all(r["engine_version"] == "anomaly-v1" for r in rows)  # AT-1: engine provenance
    assert all(r["is_synthetic"] == 1 for r in rows if r["kpi"] in SYNTHETIC_METRIC_IDS)


def test_anomaly_rows_satisfy_the_contract_and_name_the_correction(v2_build):
    rows = _q(v2_build["db"], "SELECT * FROM analytical_anomalies")
    for row in rows[:500]:
        AnomalyRow.model_validate({**row, "flagged": bool(row["flagged"]), "is_synthetic": bool(row["is_synthetic"])})
    assert {r["correction"] for r in rows} == {f"benjamini_hochberg_0.05_over_{len(rows)}_tests"}


def test_driver_contributions_are_additive_only_and_reconcile(v2_build):
    rows = _q(v2_build["db"], "SELECT * FROM driver_contributions")
    assert {r["kpi"] for r in rows} <= {"revenue", "gmv", "order_count", "freight_value", "item_count",
                                         "customer_count", "marketing_spend", "sessions"}
    groups = {}
    for r in rows:
        groups.setdefault((r["kpi"], r["dimension"], r["current_period"]), []).append(r)
    for members in groups.values():
        assert sum(m["contribution"] for m in members) == pytest.approx(members[0]["total_change"], abs=1e-6)


def test_rows_carry_the_catalog_version(v2_build):
    versions = {r["catalog_version"] for r in _q(v2_build["db"], "SELECT DISTINCT catalog_version FROM analytical_series")}
    assert versions == {catalog_version()}


def test_never_writes_into_the_real_snapshot():
    from scripts.build_analytical_tables import REAL_SNAPSHOT

    with pytest.raises(ValueError, match="real snapshot"):
        build(REAL_SNAPSHOT)
