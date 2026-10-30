"""``last_complete_period`` and the incomplete-window caveat (V2-DATA-1, V2-DATA-3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from catalog.registry import MetricRegistry
from dataset_fixtures import DB_PATH, requires_olist
from semantic.completeness import (
    CompletenessRule,
    assess_metric,
    assess_monthly_volumes,
    roll_up,
)
from sqlalchemy import create_engine

# Orders per purchase month on the Olist snapshot (scope.md section 2.1).
# 2016-11 has no orders at all; 2016-12 has one.
OLIST_MONTHLY_ORDERS = {
    "2016-09": 4,
    "2016-10": 324,
    "2016-12": 1,
    "2017-01": 800,
    "2017-02": 1780,
    "2017-03": 2682,
    "2017-04": 2404,
    "2017-05": 3700,
    "2017-06": 3245,
    "2017-07": 4026,
    "2017-08": 4331,
    "2017-09": 4285,
    "2017-10": 4631,
    "2017-11": 7544,
    "2017-12": 5673,
    "2018-01": 7269,
    "2018-02": 6728,
    "2018-03": 7211,
    "2018-04": 6939,
    "2018-05": 6873,
    "2018-06": 6167,
    "2018-07": 6292,
    "2018-08": 6512,
    "2018-09": 16,
    "2018-10": 4,
}


def _report_from(volumes, grain="month"):
    from semantic.completeness import CompletenessReport

    months = assess_monthly_volumes(volumes)
    return CompletenessReport(
        metric_id="revenue",
        grain=grain,
        catalog_version="test",
        volume_unit="orders",
        rule=CompletenessRule(),
        periods=months if grain == "month" else roll_up(months, grain),
    )


def test_last_complete_month_is_2018_08_not_max_date():
    report = _report_from(OLIST_MONTHLY_ORDERS)

    assert report.last_complete_period == "2018-08"
    flagged = {item.period for item in report.incomplete_periods}
    assert {"2016-09", "2018-09", "2018-10"} <= flagged


def test_interior_gap_and_single_order_month_are_incomplete():
    report = _report_from(OLIST_MONTHLY_ORDERS)

    gap = next(item for item in report.periods if item.period == "2016-11")
    assert gap.observed == 0 and not gap.complete
    assert not report.is_complete("2016-12")
    # The head ramp is real activity, not an artefact.
    assert report.is_complete("2016-10")


def test_complete_run_is_the_fit_window():
    report = _report_from(OLIST_MONTHLY_ORDERS)

    run = report.complete_run()
    assert run[0] == "2017-01"
    assert run[-1] == "2018-08"
    assert len(run) == 20


def test_genuine_drop_is_not_hidden_as_incomplete():
    volumes = {f"2018-0{month}": 1000 for month in range(1, 7)}
    volumes["2018-04"] = 600  # a 40% drop a diagnostic question asks about

    report = _report_from(volumes)

    assert report.is_complete("2018-04")


def test_tail_compares_against_complete_months_only():
    volumes = {"2018-06": 6000, "2018-07": 6000, "2018-08": 6000, "2018-09": 16, "2018-10": 15}

    report = _report_from(volumes)

    # 15 vs 16 would pass if 2018-09 were in the reference.
    assert not report.is_complete("2018-10")


def test_quarter_and_year_roll_up():
    quarters = _report_from(OLIST_MONTHLY_ORDERS, grain="quarter")
    years = _report_from(OLIST_MONTHLY_ORDERS, grain="year")

    assert quarters.last_complete_period == "2018-Q2"
    assert not quarters.is_complete("2018-Q3")
    assert years.last_complete_period == "2017"
    assert "2018-09" in next(i for i in years.periods if i.period == "2018").reason


def test_caveat_names_period_and_observed_volume():
    report = _report_from(OLIST_MONTHLY_ORDERS)

    caveat = report.caveat_for_window("2018-01", "2018-10")

    assert caveat is not None
    assert "2018-09 (16 orders)" in caveat
    assert "2018-10 (4 orders)" in caveat
    assert "2018-08" in caveat
    assert report.caveat_for_window("2018-01", "2018-08") is None


def test_rule_rejects_bad_input():
    with pytest.raises(ValueError):
        assess_monthly_volumes({"2018-13": 5})
    with pytest.raises(ValueError):
        assess_monthly_volumes({"2018-01": -1})
    assert assess_monthly_volumes({}) == ()


def _write_orders_db(path: Path, volumes: dict[str, int]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE orders (order_id TEXT, order_purchase_timestamp TEXT)"
        )
        rows = [
            (f"{period}-{i}", f"{period}-15 10:00:00")
            for period, count in volumes.items()
            for i in range(count)
        ]
        conn.executemany("INSERT INTO orders VALUES (?, ?)", rows)


def test_assess_metric_reads_volumes_read_only(tmp_path):
    db = tmp_path / "mini.sqlite"
    scaled = {period: max(1, count // 10) for period, count in OLIST_MONTHLY_ORDERS.items()}
    scaled["2018-09"], scaled["2018-10"] = 2, 1
    _write_orders_db(db, scaled)
    engine = create_engine(f"sqlite:///file:{db.as_posix()}?mode=ro&uri=true")
    metric = MetricRegistry.default().require("revenue")

    with engine.connect() as connection:
        report = assess_metric(connection, metric, catalog_version="v-test")

    assert report.last_complete_period == "2018-08"
    assert report.catalog_version == "v-test"
    assert report.volume_unit == "orders"


@requires_olist
def test_real_snapshot_last_complete_month():
    engine = create_engine(f"sqlite:///file:{DB_PATH.as_posix()}?mode=ro&uri=true")
    metric = MetricRegistry.default().require("revenue")

    with engine.connect() as connection:
        report = assess_metric(connection, metric, catalog_version="real")

    assert report.last_complete_period == "2018-08"
    for period in ("2016-09", "2018-09", "2018-10"):
        assert not report.is_complete(period)


def test_a_month_must_be_complete_in_every_date_table(tmp_path):
    db = tmp_path / "mixed.sqlite"
    scaled = {period: max(1, count // 10) for period, count in OLIST_MONTHLY_ORDERS.items()}
    scaled["2018-09"], scaled["2018-10"] = 2, 1
    _write_orders_db(db, scaled)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE regional_targets (state TEXT, month TEXT, revenue_target REAL)")
        conn.executemany(
            "INSERT INTO regional_targets VALUES ('SP', ?, 1.0)",
            [(period,) for period in OLIST_MONTHLY_ORDERS],
        )
    engine = create_engine(f"sqlite:///file:{db.as_posix()}?mode=ro&uri=true")
    from semantic.metrics_v2 import all_metrics

    metric = all_metrics().require("target_attainment")
    with engine.connect() as connection:
        alone = assess_metric(connection, metric, catalog_version="v")
        joint = assess_metric(
            connection,
            metric,
            catalog_version="v",
            also_date_columns=("orders.order_purchase_timestamp",),
        )

    assert alone.last_complete_period == "2018-10"  # the target table alone is full
    assert joint.last_complete_period == "2018-08"
    assert "orders.order_purchase_timestamp is incomplete" in next(
        item for item in joint.periods if item.period == "2018-09"
    ).reason
