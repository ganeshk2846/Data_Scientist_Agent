"""Precompute the analytical tables into the V2 database (GRD-12, AT-1..5).

    python scripts/build_analytical_tables.py [--db data/brazil_ecommerce_v2.sqlite]

Writes five tables, dropping and rebuilding them on every run:

* ``kpi_daily`` - every KPI per day, from SQL (numerator, denominator, value).
* ``analytical_series`` - every KPI per month, total and by each dimension,
  with the completeness flag for that month.
* ``analytical_anomalies`` - ``python.anomaly`` on every complete month that
  has 12 complete months of history, total and per dimension value, with a
  Benjamini-Hochberg correction across every test in the table.
* ``analytical_forecasts`` - ``python.forecast`` anchored on each KPI's last
  complete month, fitted only on its latest contiguous complete run.
* ``driver_contributions`` - ``python.driver`` month-over-month for additive
  KPIs. Ratio and mean KPIs are not additively decomposed (DRV-2); their
  numerator/denominator decomposition is Track 2 work.

Every figure is SQL output or registered-engine output. Nothing here asks a
model for anything (SAFE-8). The real snapshot is refused as a target.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import NormalDist

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from sqlalchemy import create_engine  # noqa: E402

from analysts.anomaly import AnomalyAnalyst  # noqa: E402
from analysts.driver import DriverAnalyst  # noqa: E402
from analysts.forecast import ENGINE_VERSION as FORECAST_VERSION  # noqa: E402
from analysts.forecast import forecast_series  # noqa: E402
from contracts.models import AnalystColumn, AnalystInput, Period, TableRef  # noqa: E402
from contracts.v2 import AnomalyRow, ForecastRow  # noqa: E402
from semantic.aggregation import AggregationRegistry  # noqa: E402
from semantic.completeness import CompletenessReport, assess_metric  # noqa: E402
from semantic.kpis import KPI_SPECS, KpiSpec  # noqa: E402
from semantic.metrics_v2 import all_metrics  # noqa: E402
from semantic.versioning import catalog_version  # noqa: E402

DEFAULT_DB = REPO_ROOT / "data" / "brazil_ecommerce_v2.sqlite"
REAL_SNAPSHOT = REPO_ROOT / "brazil_ecommerce.sqlite"
ANOMALY_VERSION = "anomaly-v1"
DRIVER_VERSION = "driver-v1"
MIN_HISTORY = 12
FDR_ALPHA = 0.05

DDL = {
    "kpi_daily": "kpi TEXT, date TEXT, value REAL, numerator REAL, denominator REAL, is_synthetic INTEGER, catalog_version TEXT",
    "analytical_series": (
        "kpi TEXT, grain TEXT, period TEXT, dimension TEXT, dimension_value TEXT, value REAL, "
        "numerator REAL, denominator REAL, complete INTEGER, is_synthetic INTEGER, catalog_version TEXT"
    ),
    "analytical_anomalies": (
        "kpi TEXT, date TEXT, grain TEXT, dimension TEXT, dimension_value TEXT, value REAL, expected REAL, "
        "delta REAL, delta_pct REAL, direction TEXT, score REAL, flagged INTEGER, correction TEXT, "
        "computed_at TEXT, engine_version TEXT, catalog_version TEXT, is_synthetic INTEGER"
    ),
    "analytical_forecasts": (
        "kpi TEXT, dimension TEXT, dimension_value TEXT, grain TEXT, anchor_period TEXT, date TEXT, "
        "yhat REAL, yhat_lower REAL, yhat_upper REAL, model TEXT, model_fallback_reason TEXT, mape REAL, "
        "computed_at TEXT, engine_version TEXT, catalog_version TEXT, is_synthetic INTEGER"
    ),
    "driver_contributions": (
        "kpi TEXT, dimension TEXT, dimension_value TEXT, current_period TEXT, comparison_period TEXT, "
        "contribution REAL, share REAL, interval_low REAL, interval_high REAL, total_change REAL, "
        "grade INTEGER, unstable INTEGER, sample_size INTEGER, reconciliation_error REAL, "
        "engine_version TEXT, catalog_version TEXT, is_synthetic INTEGER"
    ),
}
INDEXES = (
    "CREATE INDEX idx_kpi_daily ON kpi_daily(kpi, date, value)",
    "CREATE INDEX idx_series ON analytical_series(kpi, dimension, period, value)",
    "CREATE INDEX idx_anomalies_rank ON analytical_anomalies(flagged, score)",
    "CREATE INDEX idx_anomalies_kpi ON analytical_anomalies(kpi, date)",
    "CREATE INDEX idx_forecasts ON analytical_forecasts(kpi, dimension, dimension_value, date)",
    "CREATE INDEX idx_drivers ON driver_contributions(kpi, current_period, dimension)",
)


def _value(numerator, denominator) -> float | None:
    if numerator is None:
        return None
    if denominator is None:
        return float(numerator)
    return None if denominator == 0 else float(numerator) / float(denominator)


def _month_start(period: str) -> date:
    year, month = (int(part) for part in period.split("-"))
    return date(year, month, 1)


def _next_month_start(period: str) -> date:
    year, month = (int(part) for part in period.split("-"))
    return date(year + month // 12, month % 12 + 1, 1)


class _Builder:
    def __init__(self, connection, *, computed_at: str, version: str, top_n: int, horizon: int) -> None:
        self.connection = connection
        self.computed_at = computed_at
        self.version = version
        self.top_n = top_n
        self.horizon = horizon
        self.metrics = all_metrics()
        self.aggregations = AggregationRegistry()
        self.rows: dict[str, list[tuple]] = {name: [] for name in DDL}
        self._pending_anomalies: list[tuple[AnomalyRow, float]] = []

    # ------------------------------------------------------------------ #

    def completeness(self, spec: KpiSpec) -> CompletenessReport:
        metric = self.metrics.require(spec.kpi)
        extra = tuple(column for column in spec.completeness_columns if column != metric.date_column)
        return assess_metric(self.connection, metric, catalog_version=self.version, also_date_columns=extra)

    def query(self, sql: str) -> list[tuple]:
        return [tuple(row) for row in self.connection.exec_driver_sql(sql).all()]

    def series(self, spec: KpiSpec, report: CompletenessReport) -> dict[str | None, dict[str, dict[str, float | None]]]:
        """{dimension: {dimension_value: {period: value}}}; dimension None is the total."""
        out: dict[str | None, dict[str, dict[str, float | None]]] = {}
        synthetic = int(spec.is_synthetic)
        for dimension in (None, *spec.dimensions):
            values: dict[str, dict[str, float | None]] = {}
            for row in self.query(spec.sql("month", dimension)):
                if dimension is None:
                    period, numerator, denominator = row
                    member = None
                else:
                    period, member, numerator, denominator = row
                    member = "unknown" if member is None else str(member)
                if not period:
                    continue
                value = _value(numerator, denominator)
                try:
                    complete = int(report.is_complete(period))
                except KeyError:
                    complete = 0
                self.rows["analytical_series"].append((
                    spec.kpi, "month", period, dimension, member, value, numerator, denominator,
                    complete, synthetic, self.version,
                ))
                values.setdefault(member, {})[period] = value
            out[dimension] = values
        return out

    def daily(self, spec: KpiSpec) -> None:
        if "day" not in spec.grains:
            return
        for period, numerator, denominator in self.query(spec.sql("day")):
            if period:
                self.rows["kpi_daily"].append((
                    spec.kpi, period, _value(numerator, denominator), numerator, denominator,
                    int(spec.is_synthetic), self.version,
                ))

    def _top_members(self, members: dict[str, dict[str, float | None]], run: tuple[str, ...]) -> list[str]:
        complete = [
            member for member, by_period in members.items()
            if all(by_period.get(period) is not None for period in run)
        ]
        # Rank by the member's SQL total over the run; ties broken by name.
        weight = {member: sum(abs(members[member][period]) for period in run) for member in complete}
        return sorted(complete, key=lambda member: (-weight[member], member))[: self.top_n]

    def anomalies(self, spec: KpiSpec, run: tuple[str, ...], series) -> None:
        if len(run) <= MIN_HISTORY:
            return
        analyst = AnomalyAnalyst()
        for dimension, members in series.items():
            chosen = [None] if dimension is None else self._top_members(members, run)
            for member in chosen:
                by_period = members.get(member, {})
                if any(by_period.get(period) is None for period in run):
                    continue
                for position in range(MIN_HISTORY, len(run)):
                    test = run[position]
                    history = run[:position + 1]
                    table = TableRef(
                        query_id=f"{spec.kpi}-series",
                        columns=(
                            AnalystColumn(name="month", type="TEXT", role="time"),
                            AnalystColumn(name="value", type="REAL", role="measure"),
                        ),
                        row_count=len(history),
                        uri=f"analytical://{spec.kpi}",
                        rows=tuple((period, by_period[period]) for period in history),
                    )
                    output = analyst.run(AnalystInput(
                        module="anomaly",
                        params={
                            "metric": spec.kpi,
                            "grain": "month",
                            "test_window": Period(start=_month_start(test), end=_next_month_start(test)),
                            "history_window": Period(start=_month_start(run[0]), end=_month_start(test)),
                        },
                        tables={"series": table},
                        run_id=f"build-{spec.kpi}",
                        seed=0,
                    ))
                    if output.status != "ok" or output.result is None:
                        continue
                    result = output.result
                    delta = result.actual - result.expected
                    p_value = 2 * (1 - NormalDist().cdf(abs(result.robust_score)))
                    row = AnomalyRow(
                        kpi=spec.kpi, date=_month_start(test).isoformat(), grain="month",
                        dimension=dimension, dimension_value=member, value=result.actual,
                        expected=result.expected, delta=delta, delta_pct=result.deviation_pct / 100.0,
                        direction="spike" if delta >= 0 else "dip", score=result.robust_score,
                        flagged=result.verdict == "unusual", correction="pending",
                        computed_at=self.computed_at, engine_version=ANOMALY_VERSION,
                        catalog_version=self.version, is_synthetic=spec.is_synthetic,
                    )
                    self._pending_anomalies.append((row, p_value))

    def finish_anomalies(self) -> None:
        """Benjamini-Hochberg across every test in the table (ANOM-6)."""
        tests = self._pending_anomalies
        count = len(tests)
        order = sorted(range(count), key=lambda index: tests[index][1])
        survives = [False] * count
        cutoff = -1
        for rank, index in enumerate(order, start=1):
            if tests[index][1] <= FDR_ALPHA * rank / count:
                cutoff = rank
        for rank, index in enumerate(order, start=1):
            survives[index] = rank <= cutoff
        correction = f"benjamini_hochberg_{FDR_ALPHA}_over_{count}_tests"
        for (row, _), significant in zip(tests, survives, strict=True):
            self.rows["analytical_anomalies"].append((
                row.kpi, row.date, row.grain, row.dimension, row.dimension_value, row.value,
                row.expected, row.delta, row.delta_pct, row.direction, row.score,
                int(row.flagged and significant), correction, row.computed_at,
                row.engine_version, row.catalog_version, int(row.is_synthetic),
            ))

    def forecasts(self, spec: KpiSpec, run: tuple[str, ...], series) -> None:
        bounds = self.aggregations.require(spec.kpi).bounds
        targets: list[tuple[str | None, str | None]] = [(None, None)]
        dimension = "customer_state" if "customer_state" in spec.dimensions else next(iter(spec.dimensions), None)
        if dimension is not None:
            targets += [(dimension, member) for member in self._top_members(series[dimension], run)[:5]]
        for dim, member in targets:
            by_period = series[dim].get(member, {})
            if any(by_period.get(period) is None for period in run):
                continue
            fit = forecast_series(list(run), [by_period[p] for p in run], horizon=self.horizon, bounds=bounds)
            if fit.status != "ok":
                continue
            for point in fit.points:
                row = ForecastRow(
                    kpi=spec.kpi, dimension=dim, dimension_value=member, grain="month",
                    anchor_period=fit.anchor_period, ds=point.period, yhat=point.yhat,
                    yhat_lower=point.yhat_lower, yhat_upper=point.yhat_upper, model=fit.model,
                    model_fallback_reason=fit.model_fallback_reason, mape=fit.mape,
                    computed_at=self.computed_at, engine_version=FORECAST_VERSION,
                    catalog_version=self.version, is_synthetic=spec.is_synthetic,
                )
                self.rows["analytical_forecasts"].append((
                    row.kpi, row.dimension, row.dimension_value, row.grain, row.anchor_period, row.ds,
                    row.yhat, row.yhat_lower, row.yhat_upper, row.model, row.model_fallback_reason,
                    row.mape, row.computed_at, row.engine_version, row.catalog_version, int(row.is_synthetic),
                ))

    def drivers(self, spec: KpiSpec, run: tuple[str, ...], series) -> None:
        if not self.aggregations.require(spec.kpi).is_additive:
            return
        analyst = DriverAnalyst()
        recent = run[-6:]
        for dimension, members in series.items():
            if dimension is None:
                continue
            for comparison, current in zip(recent, recent[1:]):
                rows = tuple(
                    (_month_start(period).isoformat(), member, value)
                    for member, by_period in sorted(members.items())
                    for period in (comparison, current)
                    if (value := by_period.get(period)) is not None
                )
                if not rows:
                    continue
                output = analyst.run(AnalystInput(
                    module="driver",
                    params={
                        "metric": spec.kpi,
                        "current_period": Period(start=_month_start(current), end=_next_month_start(current)),
                        "comparison_period": Period(start=_month_start(comparison), end=_next_month_start(comparison)),
                        "dimensions": (dimension,),
                    },
                    tables={"contrib": TableRef(
                        query_id=f"{spec.kpi}-{dimension}",
                        columns=(
                            AnalystColumn(name="period", type="TEXT", role="time"),
                            AnalystColumn(name=dimension, type="TEXT", role="dimension"),
                            AnalystColumn(name="value", type="REAL", role="measure"),
                        ),
                        row_count=len(rows),
                        uri=f"analytical://{spec.kpi}/{dimension}",
                        rows=rows,
                    )},
                    run_id=f"build-{spec.kpi}-{dimension}",
                    seed=0,
                ))
                if output.status != "ok" or output.result is None:
                    continue
                result = output.result
                for driver in result.drivers:
                    self.rows["driver_contributions"].append((
                        spec.kpi, dimension, driver.value, current, comparison, driver.contribution,
                        driver.share, driver.interval[0], driver.interval[1], result.total_change,
                        driver.grade, int(driver.unstable), driver.sample_size, result.reconciliation_error,
                        DRIVER_VERSION, self.version, int(spec.is_synthetic),
                    ))


def _write(path: Path, rows: dict[str, list[tuple]]) -> None:
    with sqlite3.connect(path) as conn:
        for name, columns in DDL.items():
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')
            conn.execute(f'CREATE TABLE "{name}" ({columns})')
            width = columns.count(",") + 1
            conn.executemany(f'INSERT INTO "{name}" VALUES ({", ".join("?" * width)})', rows[name])
        for statement in INDEXES:
            conn.execute(statement)
        conn.execute("ANALYZE")


def build(
    db: Path = DEFAULT_DB,
    *,
    computed_at: str | None = None,
    top_n: int = 10,
    horizon: int = 3,
    kpis: Iterable[str] | None = None,
) -> dict[str, int]:
    db = Path(db).resolve()
    if db == REAL_SNAPSHOT.resolve():
        raise ValueError("analytical tables are never written into the real snapshot (V2-SYN-1)")
    if not db.is_file():
        raise FileNotFoundError(f"{db} not found; run scripts/synth/generate.py first")
    computed_at = computed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    wanted = set(kpis) if kpis is not None else None
    engine = create_engine(f"sqlite:///file:{db.as_posix()}?mode=ro&uri=true")
    with engine.connect() as connection:
        builder = _Builder(
            connection, computed_at=computed_at, version=catalog_version(), top_n=top_n, horizon=horizon
        )
        for spec in KPI_SPECS:
            if wanted is not None and spec.kpi not in wanted:
                continue
            report = builder.completeness(spec)
            run = report.complete_run()
            series = builder.series(spec, report)
            builder.daily(spec)
            builder.anomalies(spec, run, series)
            builder.forecasts(spec, run, series)
            builder.drivers(spec, run, series)
        builder.finish_anomalies()
    engine.dispose()
    _write(db, builder.rows)
    return {name: len(rows) for name, rows in builder.rows.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Precompute the V2 analytical tables.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--computed-at", default=None, help="ISO timestamp to stamp rows with")
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args(argv)
    for name, count in build(args.db, computed_at=args.computed_at, top_n=args.top_n).items():
        print(f"{name:<22}  {count:>10,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
