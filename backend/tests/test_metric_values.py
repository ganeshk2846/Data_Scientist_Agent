"""Every metric matches its known-good value in tests/metrics/*.yaml.

Each fixture value is checked against the precomputed ``analytical_series``
and, for the nine governed V1 metrics, independently against the V1
governed compiler executed through the read-only gateway. Real-snapshot
values are checked only where the snapshot is present.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from catalog import MetricRegistry
from contracts.models import GatewayConfig, Period
from dataset_fixtures import DB_PATH, requires_olist
from gateway.connection import ConnectionManager
from gateway.executor import QueryExecutor
from schema_retriever.catalog import SchemaCatalog
from semantic.kpis import KPI_SPECS
from sql.compiler import SQLCompiler

METRIC_FILES = sorted((Path(__file__).parent / "metrics").glob("*.yaml"))
SPECS = {path.stem: yaml.safe_load(path.read_text()) for path in METRIC_FILES}


def _checks(source: str):
    return [
        pytest.param(spec["metric_id"], check, id=f"{spec['metric_id']}-{check['period']}")
        for spec in SPECS.values()
        for check in spec["checks"]
        if check["source"] == source
    ]


def _period(month: str) -> Period:
    year, number = (int(part) for part in month.split("-"))
    return Period(start=f"{month}-01", end=f"{year + number // 12}-{number % 12 + 1:02d}-01")


def test_every_kpi_has_a_known_good_value():
    assert set(SPECS) == {spec.kpi for spec in KPI_SPECS}
    for name, spec in SPECS.items():
        assert spec["metric_id"] == name
        assert any(check["source"] == "fixture" for check in spec["checks"])


@pytest.mark.parametrize(("metric_id", "check"), _checks("fixture"))
def test_fixture_value_from_the_analytical_series(v2_build, metric_id, check):
    with sqlite3.connect(v2_build["db"]) as conn:
        (value,) = conn.execute(
            "SELECT value FROM analytical_series WHERE kpi = ? AND period = ? AND dimension IS NULL",
            (metric_id, check["period"]),
        ).fetchone()
    assert value == pytest.approx(check["value"], abs=check["tolerance"] or 1e-9)


@pytest.fixture(scope="module")
def v1_compiler(v2_build):
    manager = ConnectionManager(GatewayConfig(
        datasource_id="v2-fixture", dialect="sqlite", connection_url=str(v2_build["db"]), timeout_ms=5_000
    ))
    yield SQLCompiler(SchemaCatalog.from_manager(manager)), QueryExecutor(manager, max_rows=5)
    manager.dispose()


@pytest.mark.parametrize(
    ("metric_id", "check"),
    [param for param in _checks("fixture") if MetricRegistry.default().get(param.values[0]) is not None],
)
def test_fixture_value_from_the_v1_governed_compiler(v1_compiler, metric_id, check):
    compiler, executor = v1_compiler
    compiled = compiler.compile(MetricRegistry.default().require(metric_id), period=_period(check["period"]))
    execution = executor.execute(compiled.candidate.sql, query_id="Q1")
    assert execution.status == "ok", execution.error
    assert execution.rows[0][0] == pytest.approx(check["value"], abs=check["tolerance"] or 1e-9)


@requires_olist
@pytest.mark.parametrize(("metric_id", "check"), _checks("real_snapshot"))
def test_real_snapshot_value(metric_id, check):
    manager = ConnectionManager(GatewayConfig(
        datasource_id="olist", dialect="sqlite", connection_url=str(DB_PATH), timeout_ms=15_000
    ))
    try:
        compiler = SQLCompiler(SchemaCatalog.from_manager(manager))
        compiled = compiler.compile(MetricRegistry.default().require(metric_id), period=_period(check["period"]))
        execution = QueryExecutor(manager, max_rows=5).execute(compiled.candidate.sql, query_id="Q1")
    finally:
        manager.dispose()
    assert execution.rows[0][0] == pytest.approx(check["value"], abs=check["tolerance"] or 1e-9)
