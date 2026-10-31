"""The closed ``ToolName`` -> handler mapping (PL-3, ANA-2, B0, SAFE-8).

Every warehouse read goes through the existing safety chain: the governed
``SQLCompiler`` (metrics) or a fixed, reviewed dataset statement, then the
``SQLValidator`` (read-only single SELECT, table allowlist, LIMIT), then the
read-only gateway ``QueryExecutor``. No handler accepts SQL text from a plan,
a user or a model: plan params name a metric, a dataset or an analytical
table, and every literal placed into a statement is checked against a strict
pattern first.

``python.*`` steps run the Track 2 engines through ``engines.run_step`` on
typed tables built from upstream step rows. Engines never open a connection
(PL-5).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import engines
import pandas as pd
from contracts.models import ExecutionResult, MetricFilter, Period
from contracts.v2 import (
    CatalogFact,
    CatalogFactsPayload,
    EngineProvenance,
    PlanStep,
    RowsColumn,
    RowsPayload,
    ToolProvenance,
    ToolResult,
)
from engines import descriptive, prep
from engines.base import EngineData, Timer, insufficient, table_from_frame
from engines.report import (
    ChartHint,
    EngineReport,
    EngineRun,
    KeyNumber,
    ReportTable,
    confidence_from,
)
from semantic.layers import data_layer_for, synthetic_caveat
from semantic.metrics_v2 import all_metrics, is_synthetic_metric
from sql.validator import SQLValidator

_SAFE_LITERAL = re.compile(r"^[A-Za-z0-9_ .:\-]{1,64}$")
_ISO = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
DATASET_TABLES = {
    "indicators_monthly": ("marketing_spend", "web_traffic", "inventory_daily", "delivery_sla"),
    "delivery_sla": ("delivery_sla",),
    "price_panel": ("inventory_daily", "products", "price_history", "promotions", "competitor_prices"),
    "customer_features": ("customer_segments", "customers", "orders", "order_payments"),
    "reorder_items": ("inventory_daily", "price_history", "products"),
    "regional_targets": ("regional_targets",),
}
ANALYTICAL_TABLES = ("analytical_anomalies", "analytical_forecasts", "analytical_series")
ACTION_LIBRARY = (
    ("restore_driver", "Restore or reverse the change in {driver}", "intervention",
     "The co-moving driver is the lever|The relationship holds at the restored level",
     "Costs budget before the effect is confirmed|Co-movement is not proof the driver is causal",
     "Smaller if the driver only co-moved", "{metric} weekly|{driver} weekly", "A controlled test of {driver}"),
    ("focus_segment", "Concentrate effort on {segment}", "intervention",
     "The concentrated change persists|{segment} is reachable",
     "Neglects the rest of the base|Concentration may be one-off", "Depends on how concentrated the change stays",
     "{metric} for {segment}", "Next month's breakdown"),
    ("gather_evidence", "Run a controlled test before committing", "information_gathering",
     "A test window and a control group are available", "Slower to act|Small cost for stronger evidence",
     "Not sensitive: it is what raises the evidence grade", "Test versus control", "The test result"),
    ("monitor_metric", "Monitor {metric} for another complete period", "information_gathering",
     "The movement may be noise or one-off", "Delays action by a period|Costs nothing",
     "Not sensitive", "{metric} next month against its expected range", "Next month's anomaly test"),
)


def _literal(value: Any) -> str:
    text = str(value)
    if not _SAFE_LITERAL.match(text):
        raise ValueError(f"value {text!r} is not an allowlisted literal")
    return "'" + text.replace("'", "''") + "'"


def _iso(value: Any) -> str:
    text = value.isoformat() if isinstance(value, date) else str(value)
    if not _ISO.match(text):
        raise ValueError(f"{text!r} is not an ISO date")
    return "'" + text + "'"


@dataclass
class Warehouse:
    """The read-only data surface handlers may use."""

    executor: Any
    compiler: Any
    catalog: Any
    connection_factory: Callable[[], Any] | None = None
    catalog_version: str = ""
    anchor: str = "2018-08"
    registry: Any = field(default_factory=all_metrics)
    queries: list[dict[str, Any]] = field(default_factory=list)
    max_queries: int = 40

    @property
    def tables(self) -> frozenset[str]:
        return frozenset(self.catalog.table_names) if self.catalog is not None else frozenset()

    def run(self, sql: str, *, purpose: str, tables: tuple[str, ...], origin: str = "compiler") -> ExecutionResult:
        if len(self.queries) >= self.max_queries:
            raise RuntimeError(f"the run's query limit of {self.max_queries} was reached")
        validation = SQLValidator(tables, dialect="sqlite").validate(sql)
        query_id = f"Q{len(self.queries) + 1}"
        if not validation.approved:
            failed = next((check for check in validation.checks if check.status == "fail"), None)
            self.queries.append({"query_id": query_id, "sql": sql, "status": "rejected", "duration_ms": 0, "purpose": purpose, "origin": origin})
            raise ValueError(f"the validator rejected the {purpose} query: {failed.reason if failed else 'unknown'}")
        execution = self.executor.execute(sql, query_id=query_id)
        self.queries.append({"query_id": query_id, "sql": sql, "status": "ok" if execution.status in ("ok", "truncated") else "error",
                             "duration_ms": execution.duration_ms, "purpose": purpose, "origin": origin, "rows": execution.row_count,
                             "truncated": execution.status == "truncated"})
        if execution.status not in ("ok", "truncated"):
            raise RuntimeError(f"the {purpose} query returned {execution.status}: {execution.error.message if execution.error else ''}")
        return execution


@dataclass
class StepContext:
    warehouse: Warehouse
    results: dict[str, ToolResult]
    reports: dict[str, EngineReport]
    frames: dict[str, dict[str, pd.DataFrame]]
    seed: int = 0
    run_id: str = "run"
    on_engine: Callable[[PlanStep], None] | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _frame(execution: ExecutionResult) -> pd.DataFrame:
    return pd.DataFrame(list(execution.rows or ()), columns=[column.name for column in execution.columns])


def _rows_payload(query_id: str, frame: pd.DataFrame, *, truncated: bool = False) -> RowsPayload:
    columns = []
    for name in frame.columns:
        series = frame[name]
        kind = "REAL" if pd.api.types.is_float_dtype(series) else "INTEGER" if pd.api.types.is_integer_dtype(series) else "TEXT"
        role = "time" if name in {"month", "period", "date", "day", "week", "ds"} else "measure" if kind != "TEXT" else "dimension"
        columns.append(RowsColumn(name=str(name), type=kind, role=role))
    rows = tuple(tuple(_clean(value) for value in row) for row in frame.itertuples(index=False, name=None))
    return RowsPayload(query_id=query_id, columns=tuple(columns), rows=rows, row_count=len(rows), truncated=truncated)


def _clean(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _layer(tables: tuple[str, ...], *, analytical_synthetic: bool | None = None) -> tuple[str, tuple[str, ...]]:
    try:
        return data_layer_for(tables, analytical_rows_synthetic=analytical_synthetic)
    except (KeyError, ValueError):
        return "real", ()


def _rows_result(step: PlanStep, frame: pd.DataFrame, query_ids: tuple[str, ...], tables: tuple[str, ...], timer: Timer, *,
                 source: str = "sql", engine: EngineProvenance | None = None, analytical_synthetic: bool | None = None,
                 truncated: bool = False) -> ToolResult:
    layer, synthetic = _layer(tables, analytical_synthetic=analytical_synthetic)
    payload = _rows_payload(query_ids[0], frame, truncated=truncated)
    status = "ok" if payload.row_count else "empty"
    return ToolResult(
        step_id=step.step_id, tool=step.tool, status=status, produces="rows", rows=payload,
        provenance=ToolProvenance(source=source, query_ids=query_ids, engine=engine, input_step_ids=step.depends_on,
                                  deterministic=True, data_layer=layer, synthetic_tables=synthetic),  # type: ignore[arg-type]
        caveats=tuple(caveat for caveat in (synthetic_caveat(synthetic),) if caveat) + (("The result hit the row cap and is truncated.",) if truncated else ()),
        reason=None if status == "ok" else "The query returned no rows for this scope.",
        duration_ms=timer.elapsed_ms(),
    )


def _period(params: Mapping[str, Any], key: str = "period") -> Period | None:
    value = params.get(key)
    return Period.model_validate(value) if value else None


def _month_key(value: date) -> str:
    return f"{value:%Y-%m}"


# --------------------------------------------------------------------------- #
# sql
# --------------------------------------------------------------------------- #


def _sql(step: PlanStep, ctx: StepContext) -> EngineRun:
    timer = Timer()
    params = step.params
    warehouse = ctx.warehouse
    if params.get("kind") == "dataset":
        return _dataset(step, ctx, timer)
    metric = warehouse.registry.require(params["metric_id"])
    filters = []
    for item in params.get("filters", ()):
        dimension = next((d for d in metric.allowed_dimensions if d.name == item["dimension"]), None)
        if dimension is None:
            continue
        values = tuple(str(value) for value in item["values"])
        filters.append(MetricFilter(table=dimension.table, column=dimension.column, operator="in" if len(values) > 1 else "=",
                                    value=values if len(values) > 1 else values[0]))
    period = _period(params)
    compiled = warehouse.compiler.compile(metric, dimensions=tuple(params.get("dimensions", ())), filters=tuple(filters),
                                          period=period, time_grain=params.get("grain") or "month")
    if not compiled.validation.approved:
        raise ValueError("the compiled metric query failed validation")
    sql = re.sub(r"\bLIMIT\s+\d+\s*$", "LIMIT 5000", compiled.candidate.sql.strip())
    execution = warehouse.run(sql, purpose=f"{metric.metric_id} query", tables=tuple(warehouse.tables))
    frame = _frame(execution)
    tables = tuple(sorted({name for name in warehouse.tables if re.search(rf'"{name}"', sql)})) or (metric.base_table,)
    ctx.frames[step.step_id] = {"rows": frame}
    summary = params.get("summary", "none")
    if summary != "none" and not frame.empty:
        result = _summarise(step, ctx, frame, metric.metric_id, execution.query_id, tables, summary, timer)
        if result is not None:
            return result
    result = _rows_result(step, frame, (execution.query_id,), tables, timer, truncated=execution.status == "truncated")
    report = _rows_report(metric.metric_id, frame, step)
    return EngineRun(result, report)


def _summarise(step, ctx, frame, metric_id, query_id, tables, summary, timer) -> EngineRun | None:
    """Run the descriptive engine (SQL over the fetched rows) for trend, rank and comparisons."""
    params = step.params
    time_column = next((name for name in ("month", "week", "day", "date", "quarter", "year") if name in frame.columns), None)
    dims = [name for name in params.get("dimensions", ()) if name in frame.columns]
    measure = metric_id if metric_id in frame.columns else frame.columns[-1]
    source = table_from_frame(frame, query_id=query_id, roles={name: "time" for name in ([time_column] if time_column else [])})
    data = EngineData(tables={"rows": source}, source_tables=tables, seed=ctx.seed, run_id=ctx.run_id, step_id=step.step_id,
                      input_step_ids=step.depends_on)
    aggregation = "avg" if metric_id in {"aov", "review_score", "cancellation_rate", "conversion_rate", "stockout_rate", "return_rate", "margin", "target_attainment"} else "sum"
    if summary == "trend" and time_column:
        request = {"operation": "trend", "measure": measure, "aggregation": aggregation, "period_column": time_column,
                   "grain": "month" if time_column == "month" else "day" if time_column in {"day", "date"} else "year"}
        if params.get("summary_period"):
            window = Period.model_validate(params["summary_period"])
            fmt = _month_key if time_column == "month" else (lambda value: value.isoformat())
            request.update(start=fmt(window.start), end=fmt(window.end))
    elif summary == "rank" and dims:
        request = {"operation": "rank", "measure": measure, "aggregation": aggregation, "dimensions": tuple(dims), "top_n": params.get("top_n", 10)}
    elif summary == "compare" and time_column and params.get("current") and params.get("comparison"):
        current, comparison = Period.model_validate(params["current"]), Period.model_validate(params["comparison"])
        fmt = (lambda value: _month_key(value)) if time_column == "month" else (lambda value: value.isoformat())
        request = {"operation": "aggregate", "measure": measure, "aggregation": aggregation, "dimensions": tuple(dims),
                   "period_column": time_column, "start": fmt(current.start), "end": fmt(current.end),
                   "comparison_start": fmt(comparison.start), "comparison_end": fmt(comparison.end)}
    elif summary == "aggregate" and dims:
        request = {"operation": "aggregate", "measure": measure, "aggregation": aggregation, "dimensions": tuple(dims)}
    else:
        return None
    run = descriptive.execute(request, data)
    if run.result.status not in ("ok", "empty"):
        return None
    return run


def _rows_report(metric_id: str, frame: pd.DataFrame, step: PlanStep) -> EngineReport:
    numbers = []
    if not frame.empty:
        value_column = metric_id if metric_id in frame.columns else frame.columns[-1]
        if len(frame) == 1:
            numbers.append(KeyNumber(name="value", value=float(frame[value_column].iloc[0]) if frame[value_column].iloc[0] is not None else None,
                                     label=metric_id))
        else:
            for _, row in frame.head(5).iterrows():
                label = " / ".join(str(row[name]) for name in frame.columns if name != value_column)
                value = row[value_column]
                numbers.append(KeyNumber(name=f"value:{label}", value=float(value) if value is not None else None, label=label))
    return EngineReport(
        engine="sql", method="governed_sql",
        tables=(ReportTable(name="rows", columns=tuple(str(name) for name in frame.columns) or ("value",),
                            rows=tuple(tuple(_clean(v) for v in row) for row in frame.head(200).itertuples(index=False, name=None))),),
        key_numbers=tuple(numbers), assumptions=("Figures come from the governed metric query.",),
        confidence=confidence_from(sample_size=len(frame), basis="Measured values from SQL."),
        chart_hint=ChartHint(kind="bar" if len(frame) > 1 else "table", table="rows", x=str(frame.columns[0]) if len(frame.columns) else "value",
                             y=(str(frame.columns[-1]) if len(frame.columns) else "value",), title=metric_id),
    )


# Business priors for the synthetic indicators: the direction each one is expected to push an
# outcome class. They only decide whether a candidate's move is *consistent* with the outcome's
# measured direction (a candidate moving the other way is never named as consistent); they are
# not estimates and carry no number into an answer. boleto_share has no prior anywhere.
_VOLUME = {"revenue", "gmv", "order_count", "item_count", "customer_count", "sessions", "conversion_rate"}
_PRICE_LIKE = {"aov", "average_selling_price", "margin"}
_SERVICE_BAD = {"return_rate", "cancellation_rate"}
_INDICATOR_PRIORS: dict[str, dict[str, int]] = {
    "spend_*": {**dict.fromkeys(_VOLUME - {"conversion_rate"}, 1)},
    "sessions": {**dict.fromkeys(_VOLUME - {"sessions", "conversion_rate"}, 1)},
    "conversion_rate": {**dict.fromkeys(_VOLUME - {"sessions", "conversion_rate"}, 1)},
    "promo_discount": {**dict.fromkeys(_VOLUME - {"sessions"}, 1), **dict.fromkeys(_PRICE_LIKE, -1)},
    "stockout_rate": {**dict.fromkeys(_VOLUME - {"sessions", "conversion_rate"}, -1)},
    "delay_days": {"review_score": -1, **dict.fromkeys(_SERVICE_BAD, 1)},
    "sla_breach_rate": {"review_score": -1, **dict.fromkeys(_SERVICE_BAD, 1)},
}


def indicator_sign(indicator: str, metric: str | None) -> int | None:
    """Expected sign of an indicator's effect on ``metric`` (None when there is no prior)."""
    priors = _INDICATOR_PRIORS.get("spend_*" if indicator.startswith("spend_") else indicator, {})
    return priors.get(metric or "")


def _dataset(step: PlanStep, ctx: StepContext, timer: Timer) -> EngineRun:
    params = step.params
    name = params["dataset"]
    warehouse = ctx.warehouse
    missing = [table for table in DATASET_TABLES[name] if table not in warehouse.tables]
    if missing:
        return _not_available(step, timer, f"The {name} dataset needs the synthetic tables {', '.join(missing)}, which this database does not hold.")
    period = _period(params)
    start = _iso(period.start if period else "2016-09-01")
    end = _iso(period.end if period else "2018-11-01")
    tables = DATASET_TABLES[name]
    frames: dict[str, pd.DataFrame] = {}
    query_ids: list[str] = []

    def read(key: str, sql: str, used: tuple[str, ...]) -> None:
        execution = warehouse.run(sql, purpose=f"{name}.{key}", tables=used, origin="compiler")
        frames[key] = _frame(execution)
        query_ids.append(execution.query_id)

    if name == "indicators_monthly":
        read("spend", f"SELECT substr(date, 1, 7) AS month, channel AS indicator, SUM(spend) AS value FROM marketing_spend "
                      f"WHERE date >= {start} AND date < {end} GROUP BY 1, 2 ORDER BY 1 LIMIT 5000", ("marketing_spend",))
        read("traffic", f"SELECT substr(date, 1, 7) AS month, SUM(sessions) AS sessions, AVG(conversion_rate) AS conversion_rate, "
                        f"AVG(boleto_share) AS boleto_share FROM web_traffic WHERE date >= {start} AND date < {end} GROUP BY 1 ORDER BY 1 LIMIT 5000",
             ("web_traffic",))
        read("stock", f"SELECT substr(date, 1, 7) AS month, AVG(stockout_flag) AS stockout_rate FROM inventory_daily "
                      f"WHERE date >= {start} AND date < {end} GROUP BY 1 ORDER BY 1 LIMIT 5000", ("inventory_daily",))
        read("delivery", f"SELECT substr(date, 1, 7) AS month, AVG(actual_days - promised_days) AS delay_days, AVG(sla_breach_flag) AS sla_breach_rate "
                         f"FROM delivery_sla WHERE date >= {start} AND date < {end} GROUP BY 1 ORDER BY 1 LIMIT 5000", ("delivery_sla",))
        wide = frames["spend"].pivot_table(index="month", columns="indicator", values="value", aggfunc="sum").add_prefix("spend_").reset_index()
        for key in ("traffic", "stock", "delivery"):
            wide = wide.merge(frames[key], on="month", how="outer")
        if "promotions" in warehouse.tables:
            # Discount-weighted promotion days per calendar day of the month (0 when nothing ran).
            read("promotions", f"SELECT category, start_date, end_date, discount_pct FROM promotions WHERE end_date >= {start} "
                               f"AND start_date < {end} LIMIT 5000", ("promotions",))
            wide = wide.merge(prep.monthly_promotion_intensity(frames["promotions"], wide["month"]), on="month", how="left")
            wide["promo_discount"] = wide["promo_discount"].fillna(0.0)
        frame = wide.sort_values("month").reset_index(drop=True)
    elif name == "delivery_sla":
        read("rows", f"SELECT date, carrier, state AS customer_state, sla_breach_flag AS numerator, 1 AS denominator, "
                     f"actual_days - promised_days AS delay_days, freight_cost FROM delivery_sla WHERE date >= {start} AND date < {end} "
                     f"ORDER BY date LIMIT 200000", ("delivery_sla",))
        frame = frames["rows"]
    elif name == "price_panel":
        read("inventory", "SELECT date, category, units_sold, stockout_flag FROM inventory_daily ORDER BY date LIMIT 200000", ("inventory_daily",))
        read("products", "SELECT product_id, product_category_name FROM products LIMIT 200000", ("products",))
        read("prices", "SELECT product_id, date, price FROM price_history LIMIT 200000", ("price_history",))
        read("promotions", "SELECT promo_id, category, start_date, end_date, discount_pct FROM promotions LIMIT 200000", ("promotions",))
        read("competitor", "SELECT substr(cp.date, 1, 7) || '-01' AS date, p.product_category_name AS category, AVG(cp.price) AS competitor_price "
                           "FROM competitor_prices AS cp JOIN products AS p ON p.product_id = cp.product_id GROUP BY 1, 2 LIMIT 200000",
             ("competitor_prices", "products"))
        inventory = frames["inventory"]
        list_price = prep.daily_list_price(frames["prices"], frames["products"], inventory["date"])
        discount = prep.daily_discount(frames["promotions"], inventory["date"], inventory["category"])
        sales = prep.category_sales(inventory, list_price, discount)
        ctx.frames[step.step_id] = {"sales": sales, "competitor": frames["competitor"]}
        frame = sales
    elif name == "customer_features":
        read("rows", "SELECT cs.customer_unique_id AS customer_unique_id, cs.segment AS segment, cs.ltv_band AS ltv_band, "
                     "cs.acquisition_channel AS acquisition_channel, COUNT(DISTINCT o.order_id) AS orders, SUM(op.payment_value) AS revenue "
                     "FROM customer_segments AS cs JOIN customers AS c ON c.customer_unique_id = cs.customer_unique_id "
                     "JOIN orders AS o ON o.customer_id = c.customer_id JOIN order_payments AS op ON op.order_id = o.order_id "
                     "GROUP BY 1, 2, 3, 4 LIMIT 200000", ("customer_segments", "customers", "orders", "order_payments"))
        frame = frames["rows"]
    elif name == "reorder_items":
        anchor_end = _iso(f"{warehouse.anchor}-28")
        read("stock", f"SELECT category, stock_on_hand FROM inventory_daily WHERE date = (SELECT MAX(date) FROM inventory_daily WHERE date <= {anchor_end}) LIMIT 500",
             ("inventory_daily",))
        read("demand", f"SELECT category, AVG(units_sold) AS daily_units FROM inventory_daily WHERE stockout_flag = 0 AND date > date({anchor_end}, '-30 day') "
                       f"AND date <= {anchor_end} GROUP BY 1 LIMIT 500", ("inventory_daily",))
        read("prices", "SELECT p.product_category_name AS category, AVG(ph.price) AS price, AVG(ph.unit_cost) AS unit_cost FROM price_history AS ph "
                       "JOIN products AS p ON p.product_id = ph.product_id GROUP BY 1 LIMIT 500", ("price_history", "products"))
        merged = frames["stock"].merge(frames["demand"], on="category").merge(frames["prices"], on="category")
        frame = pd.DataFrame({"item": merged["category"], "forecast_demand": merged["daily_units"] * 14, "stock_on_hand": merged["stock_on_hand"],
                              "unit_cost": merged["unit_cost"], "unit_margin": merged["price"] - merged["unit_cost"]})
    elif name == "regional_targets":
        clauses = [f"month >= '{_month_key(period.start)}'" if period else "1 = 1", f"month < '{_month_key(period.end)}'" if period else "1 = 1"]
        for item in params.get("filters", ()):
            if item["dimension"] == "customer_state":
                clauses.append("state IN (" + ", ".join(_literal(value) for value in item["values"]) + ")")
        read("rows", f"SELECT state AS customer_state, month, revenue_target FROM regional_targets WHERE {' AND '.join(clauses)} LIMIT 5000",
             ("regional_targets",))
        frame = frames["rows"]
    else:  # pragma: no cover - the params schema closes the set
        raise ValueError(f"unknown dataset {name!r}")
    ctx.frames.setdefault(step.step_id, {})["rows"] = frame
    result = _rows_result(step, frame, tuple(query_ids), tables, timer)
    return EngineRun(result, EngineReport(engine="sql", method=f"dataset.{name}",
                                          tables=(ReportTable(name="rows", columns=tuple(str(c) for c in frame.columns) or ("value",),
                                                              rows=tuple(tuple(_clean(v) for v in row) for row in frame.head(20).itertuples(index=False, name=None))),),
                                          key_numbers=(KeyNumber(name="rows", value=float(len(frame)), label="rows"),),
                                          assumptions=(f"The {name} dataset is a fixed, reviewed read-only query set.",),
                                          confidence=confidence_from(sample_size=len(frame), basis="Measured rows."),
                                          chart_hint=ChartHint(kind="table", table="rows", x=str(frame.columns[0]) if len(frame.columns) else "value",
                                                               y=(str(frame.columns[-1]) if len(frame.columns) else "value",), title=name)))


def _not_available(step: PlanStep, timer: Timer, reason: str) -> EngineRun:
    result = ToolResult(step_id=step.step_id, tool=step.tool, status="insufficient_evidence", produces=step.produces,
                        provenance=ToolProvenance(source="sql" if step.tool in ("sql", "analytical_table") else "catalog",
                                                  input_step_ids=step.depends_on, deterministic=True),
                        reason=reason, duration_ms=timer.elapsed_ms())
    return EngineRun(result, EngineReport(engine=step.tool, method="unavailable", assumptions=(reason,),
                                          confidence=confidence_from(basis=reason).model_copy(update={"level": "insufficient", "score": 0.0})))


# --------------------------------------------------------------------------- #
# analytical_table
# --------------------------------------------------------------------------- #


def _analytical(step: PlanStep, ctx: StepContext) -> EngineRun:
    timer = Timer()
    params = step.params
    warehouse = ctx.warehouse
    table = params["table"]
    if table not in warehouse.tables:
        return _not_available(step, timer, f"The precomputed {table} table is not in this database.")
    version = _literal(warehouse.catalog_version) if warehouse.catalog_version else None
    where = [f"catalog_version = {version}"] if version else []
    if params.get("kpi"):
        where.append(f"kpi = {_literal(params['kpi'])}")
    if table == "analytical_anomalies":
        if params.get("flagged_only"):
            where.append("flagged = 1")
        sql = ("SELECT kpi, date, dimension, dimension_value, value, expected, delta, delta_pct, direction, score, correction, "
               "engine_version, is_synthetic, COUNT(*) OVER () AS total_flagged FROM analytical_anomalies" + (f" WHERE {' AND '.join(where)}" if where else "")
               + f" ORDER BY ABS(score) DESC, kpi, date LIMIT {int(params.get('limit', 50))}")
        engine_name = "python.anomaly"
    elif table == "analytical_forecasts":
        where.append("dimension IS NULL")
        sql = ("SELECT kpi, anchor_period, date AS ds, yhat, yhat_lower, yhat_upper, model, model_fallback_reason, mape, engine_version, is_synthetic "
               "FROM analytical_forecasts WHERE " + " AND ".join(where) + f" ORDER BY date LIMIT {int(params.get('limit', 50))}")
        engine_name = "python.forecast"
    else:
        where.append(f"grain = {_literal(params.get('grain', 'month'))}")
        where.append("complete = 1")
        if params.get("dimension"):
            where.append(f"dimension = {_literal(params['dimension'])}")
            if params.get("dimension_values"):
                where.append("dimension_value IN (" + ", ".join(_literal(value) for value in params["dimension_values"]) + ")")
        else:
            where.append("dimension IS NULL")
        period = _period(params)
        if period is not None:
            where.append(f"period >= {_literal(_month_key(period.start))}")
            where.append(f"period < {_literal(_month_key(period.end))}")
        sql = ("SELECT period, dimension_value, value, numerator, denominator, is_synthetic FROM analytical_series WHERE "
               + " AND ".join(where) + f" ORDER BY period, dimension_value LIMIT {int(params.get('limit', 5000))}")
        engine_name = None
    execution = warehouse.run(sql, purpose=f"{table} read", tables=(table,), origin="compiler")
    frame = _frame(execution)
    ctx.frames[step.step_id] = {"rows": frame}
    synthetic = bool(len(frame)) and "is_synthetic" in frame and bool(frame["is_synthetic"].astype(bool).any())
    if engine_name is not None and frame.empty and version:
        return _not_available(step, timer, f"No {table} rows match catalog version {warehouse.catalog_version}; the cache is stale (AT-2).")
    engine = None
    source = "sql"
    if engine_name is not None:
        versions = sorted(set(frame["engine_version"].astype(str))) if not frame.empty else ["unknown"]
        engine = EngineProvenance(name=engine_name, version=versions[0], method="precomputed", seed=0)  # type: ignore[arg-type]
        source = "engine"
    tables_read = (table,)
    result = _rows_result(step, frame.drop(columns=[c for c in ("is_synthetic",) if c in frame]) if engine_name is None else frame,
                          (execution.query_id,), tables_read, timer, source=source, engine=engine, analytical_synthetic=synthetic)
    report = _analytical_report(table, frame, params)
    return EngineRun(result, report)


def _analytical_report(table: str, frame: pd.DataFrame, params: Mapping[str, Any]) -> EngineReport:
    numbers: list[KeyNumber] = []
    chart = None
    if table == "analytical_anomalies" and not frame.empty:
        numbers.append(KeyNumber(name="flagged", value=float(frame["total_flagged"].iloc[0]), label="flagged movements"))
        numbers.append(KeyNumber(name="listed", value=float(len(frame)), label="movements listed"))
        for _, row in frame.head(5).iterrows():
            label = f"{row['kpi']} {str(row['date'])[:7]}" + (f" {row['dimension_value']}" if row["dimension_value"] else "")
            numbers.append(KeyNumber(name=f"delta_pct:{label}", value=float(row["delta_pct"]) * 100.0 if row["delta_pct"] is not None else None, unit="%",
                                     label=f"{label} ({row['direction']})"))
        chart = ChartHint(kind="bar", table="anomalies", x="kpi", y=("score",), series="direction", title="Spikes and dips across all months")
    elif table == "analytical_forecasts" and not frame.empty:
        last = frame.iloc[-1]
        numbers += [KeyNumber(name="final_yhat", value=float(last["yhat"]), label=f"forecast {last['ds']}"),
                    KeyNumber(name="final_lower", value=float(last["yhat_lower"]), label="interval low"),
                    KeyNumber(name="final_upper", value=float(last["yhat_upper"]), label="interval high"),
                    KeyNumber(name="backtest_mape", value=float(last["mape"]) if last["mape"] is not None else None, label="backtest MAPE"),
                    KeyNumber(name="horizon", value=float(len(frame)), label="forecast periods")]
        chart = ChartHint(kind="forecast_fan", table="forecast", x="ds", y=("yhat", "yhat_lower", "yhat_upper"), title=f"{params.get('kpi')} forecast")
    elif not frame.empty:
        numbers.append(KeyNumber(name="periods", value=float(len(frame)), label="periods"))
        chart = ChartHint(kind="line", table="series", x="period", y=("value",), title=f"{params.get('kpi')} series")
    name = {"analytical_anomalies": "anomalies", "analytical_forecasts": "forecast"}.get(table, "series")
    return EngineReport(
        engine="analytical_table", method=f"{table}.read",
        tables=(ReportTable(name=name, columns=tuple(str(c) for c in frame.columns) or ("value",),
                            rows=tuple(tuple(_clean(v) for v in row) for row in frame.head(50).itertuples(index=False, name=None))),),
        key_numbers=tuple(numbers),
        assumptions=("Read from the precomputed analytical layer; every row is engine output under its engine version (AT-1).",),
        confidence=confidence_from(sample_size=len(frame), basis="Precomputed engine output, current catalog version."),
        chart_hint=chart,
    )


# --------------------------------------------------------------------------- #
# catalog
# --------------------------------------------------------------------------- #


def _synthetic_note(tables: tuple[str, ...]) -> str:
    from semantic.layers import synthetic_caveat

    return synthetic_caveat(list(tables)) or f"Based on synthetic data: {', '.join(tables)}."


def _catalog(step: PlanStep, ctx: StepContext) -> EngineRun:
    timer = Timer()
    lookup = step.params["lookup"]
    warehouse = ctx.warehouse
    facts: list[CatalogFact] = []
    text_rows: list[tuple[Any, ...]] = []
    if lookup == "warehouse":
        from semantic.discovery import catalog_facts, describe_warehouse

        if warehouse.connection_factory is None:
            return _not_available(step, timer, "No catalog connection is configured.")
        with warehouse.connection_factory() as connection:
            description = describe_warehouse(connection)
        payload = catalog_facts(description)
        facts = list(payload.facts)
        text_rows = [(table.name, table.layer, table.row_count, table.date_min, table.date_max) for table in description.tables if table.present]
        ctx.frames[step.step_id] = {"description": description}  # type: ignore[dict-item]
    elif lookup == "metric_definition":
        for metric_id in step.params.get("metric_ids", ()):
            metric = warehouse.registry.get(metric_id)
            if metric is None:
                continue
            facts.append(CatalogFact(key=f"metric.{metric_id}.definition", value={
                "name": metric.name, "formula": metric.formula, "base_table": metric.base_table, "date_column": metric.date_column,
                "dimensions": [d.name for d in metric.allowed_dimensions], "required_filters": list(metric.required_filters),
                "caveats": list(metric.caveats), "is_synthetic": is_synthetic_metric(metric_id)}, source="catalog"))
            text_rows.append((metric_id, metric.name, metric.base_table, ", ".join(d.name for d in metric.allowed_dimensions)))
    elif lookup == "table":
        from semantic.discovery import describe_table

        synthetic_read: tuple[str, ...] = ()

        if warehouse.connection_factory is None:
            return _not_available(step, timer, "No catalog connection is configured.")
        with warehouse.connection_factory() as connection:
            detail = describe_table(connection, step.params.get("table") or "")
        if detail is not None:
            table = detail.table
            facts.append(CatalogFact(key=f"table.{table.name}.layer", value=table.layer, source="catalog"))
            facts.append(CatalogFact(key=f"table.{table.name}.grain", value=table.grain, source="catalog"))
            facts.append(CatalogFact(key=f"table.{table.name}.columns", value=[column.name for column in detail.columns], source="catalog"))
            facts.append(CatalogFact(key=f"table.{table.name}.metrics", value=list(detail.metrics), source="catalog"))
            if table.present:
                facts.append(CatalogFact(key=f"table.{table.name}.row_count", value=table.row_count, source="sql"))
            if table.date_min:
                facts.append(CatalogFact(key=f"table.{table.name}.date_range", value=[table.date_min, table.date_max], source="sql"))
            if table.layer == "synthetic" and table.present:
                synthetic_read = (table.name,)  # SY-1/SY-2: computed from the table actually read
            text_rows = [("table", table.name), ("layer", table.layer), ("subject", table.subject), ("grain", table.grain),
                         ("description", table.description), ("present", "yes" if table.present else "no"),
                         ("rows", table.row_count), ("from", table.date_min), ("to", table.date_max),
                         ("keys", ", ".join(detail.key_columns)), ("columns", ", ".join(column.name for column in detail.columns)),
                         ("metrics", ", ".join(detail.metrics)), *(("example", question) for question in detail.example_questions)]
    elif lookup == "metrics":
        from semantic.discovery import example_questions

        for metric in warehouse.registry.metrics:
            synthetic = is_synthetic_metric(metric.metric_id)
            dimensions = [d.name for d in metric.allowed_dimensions if d.name not in ("month", "year")]
            facts.append(CatalogFact(key=f"metric.{metric.metric_id}", value={"name": metric.name, "base_table": metric.base_table,
                                                                             "dimensions": dimensions, "is_synthetic": synthetic},
                                     source="catalog"))
            examples = example_questions(metric.metric_id)
            text_rows.append((metric.metric_id, metric.name, "synthetic" if synthetic else "real", metric.base_table, ", ".join(dimensions),
                              examples[0] if examples else ""))
    else:
        for action_id, title, kind, *_ in ACTION_LIBRARY:
            facts.append(CatalogFact(key=f"action.{action_id}", value={"title": title, "kind": kind}, source="catalog"))
            text_rows.append((action_id, title, kind))
    payload = CatalogFactsPayload(catalog_version=warehouse.catalog_version or "unknown", facts=tuple(facts))
    result = ToolResult(step_id=step.step_id, tool="catalog", status="ok" if facts else "insufficient_evidence", produces="catalog_facts",
                        catalog_facts=payload if facts else None,
                        provenance=ToolProvenance(source="catalog", input_step_ids=step.depends_on, deterministic=True,
                                                  **({"data_layer": "synthetic", "synthetic_tables": synthetic_read}
                                                     if lookup == "table" and synthetic_read else {})),
                        caveats=(_synthetic_note(synthetic_read),) if lookup == "table" and synthetic_read else (),
                        reason=None if facts else "The catalog holds nothing for this lookup.", duration_ms=timer.elapsed_ms())
    columns = {"warehouse": ("table", "layer", "rows", "from", "to"), "metric_definition": ("metric_id", "name", "base_table", "dimensions"),
               "action_library": ("action_id", "title", "kind"), "table": ("item", "value"),
               "metrics": ("metric_id", "name", "layer", "base_table", "dimensions", "example")}[lookup]
    report = EngineReport(engine="catalog", method=f"catalog.{lookup}",
                          tables=(ReportTable(name="catalog", columns=columns, rows=tuple(text_rows)),),
                          key_numbers=(KeyNumber(name="facts", value=float(len(facts)), label="catalog facts"),),
                          assumptions=("Answered from the catalog and fixed count queries; no figure is generated.",),
                          confidence=confidence_from(sample_size=len(facts), basis="Catalog facts."),
                          chart_hint=ChartHint(kind="table", table="catalog", x=columns[0], y=(columns[-1],), title="Catalog"))
    return EngineRun(result, report)


# --------------------------------------------------------------------------- #
# python.* engines
# --------------------------------------------------------------------------- #


def _upstream(ctx: StepContext, step: PlanStep, kind: str = "rows") -> pd.DataFrame | None:
    for dep in step.depends_on:
        frames = ctx.frames.get(dep)
        if frames and kind in frames and isinstance(frames[kind], pd.DataFrame):
            return frames[kind]
    return None


def _source_tables(ctx: StepContext, step: PlanStep) -> tuple[str, ...]:
    tables: list[str] = []
    for dep in step.depends_on:
        result = ctx.results.get(dep)
        if result is not None:
            tables.extend(result.provenance.synthetic_tables)
    return tuple(dict.fromkeys(tables))


def _query_ids(ctx: StepContext, step: PlanStep) -> tuple[str, ...]:
    ids: list[str] = []
    for dep in step.depends_on:
        result = ctx.results.get(dep)
        if result is not None:
            ids.extend(result.provenance.query_ids)
    return tuple(dict.fromkeys(ids)) or ("engine-input",)


def _series_frame(frame: pd.DataFrame, metric: str, *, dimension: str | None = None) -> pd.DataFrame:
    """Normalise upstream rows to period/value (+numerator/denominator, +dimension)."""
    out = frame.copy()
    if "period" in out.columns and "month" not in out.columns:
        out = out.rename(columns={"period": "month"})
    if metric in out.columns and "value" not in out.columns:
        out = out.rename(columns={metric: "value"})
    if dimension and "dimension_value" in out.columns:
        out = out.rename(columns={"dimension_value": dimension})
    if "month" in out.columns:
        out["month"] = out["month"].astype(str).str[:7] + "-01"
    keep = [name for name in ("month", dimension, "value", "numerator", "denominator") if name and name in out.columns]
    out = out[keep]
    if "numerator" in out and out["numerator"].isna().all():
        out = out.drop(columns=["numerator", "denominator"], errors="ignore")
    return out.dropna(subset=["value"]) if "value" in out else out


def _engine_data(ctx: StepContext, step: PlanStep, tables: Mapping[str, Any]) -> EngineData:
    return EngineData(tables={name: (value if not isinstance(value, pd.DataFrame) else
                                     table_from_frame(value, query_id=_query_ids(ctx, step)[0],
                                                      roles={c: "time" for c in ("month", "date", "period") if c in value.columns}))
                              for name, value in tables.items()},
                      source_tables=_source_tables(ctx, step), seed=ctx.seed, run_id=ctx.run_id, step_id=step.step_id,
                      input_step_ids=step.depends_on,
                      # A precomputed table appears in synthetic_tables only when its rows were synthetic (AT-5).
                      analytical_rows_synthetic=True if any(name in ANALYTICAL_TABLES for name in _source_tables(ctx, step)) else None)


def _engine(step: PlanStep, ctx: StepContext) -> EngineRun:
    timer = Timer()
    if ctx.on_engine is not None:
        ctx.on_engine(step)
    params = {key: value for key, value in step.params.items() if key != "bind"}
    bind = step.params.get("bind", {})
    tool = step.tool
    metric = params.get("metric", "value")
    frame = _upstream(ctx, step)

    def fail(reason: str) -> EngineRun:
        sources = _source_tables(ctx, step)
        layer_data = EngineData(tables={}, source_tables=sources, step_id=step.step_id, input_step_ids=step.depends_on,
                                analytical_rows_synthetic=True if any(name in ANALYTICAL_TABLES for name in sources) else None)
        return insufficient(tool=tool, reason=reason, data=layer_data, timer=timer, engine_version="executor-2.0.0", method="binding")  # type: ignore[arg-type]

    if tool in ("python.forecast", "python.anomaly"):
        if frame is None or frame.empty:
            return fail("The upstream series step returned no rows.")
        series = _series_frame(frame, metric)
        if "dimension_value" in frame.columns or any(name in series.columns for name in ("customer_state",)):
            series = series.groupby("month", as_index=False).sum(numeric_only=True)
        data = _engine_data(ctx, step, {"series": series})
        return engines.run_step(step.model_copy(update={"params": params}), data)

    if tool == "python.driver":
        if frame is None or frame.empty:
            return fail("The upstream rows for the driver step are empty.")
        dimension = params.get("dimensions", ["customer_state"])[0]
        window_note = None
        if "date" in frame.columns and "carrier" in frame.columns:
            contrib = frame.copy()
            if bind.get("auto_window"):
                # No window was named: test the month with the highest breach rate in the data read.
                monthly = contrib.assign(month=contrib["date"].astype(str).str[:7]).groupby("month")[["numerator", "denominator"]].sum()
                monthly = monthly[monthly["denominator"] > 0]
                if len(monthly) >= 2:
                    rate = (monthly["numerator"] / monthly["denominator"]).iloc[1:]
                    peak = str(rate.idxmax())
                    start = date(int(peak[:4]), int(peak[5:7]), 1)
                    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
                    previous = date(start.year - (start.month == 1), (start.month - 2) % 12 + 1, 1)
                    params["current_period"] = {"start": start.isoformat(), "end": end.isoformat()}
                    params["comparison_period"] = {"start": previous.isoformat(), "end": start.isoformat()}
                    window_note = f"No window was named, so {peak}, the month with the highest SLA breach rate, was compared with the month before."
        else:
            contrib = _series_frame(frame, metric, dimension=dimension)
        if params.get("aggregation") == "ratio" and "numerator" not in contrib.columns:
            params["aggregation"] = "sum"
        tables: dict[str, Any] = {"contrib": contrib}
        if "indicators_from" in bind and bind["indicators_from"] in ctx.frames:
            wide = ctx.frames[bind["indicators_from"]].get("rows")
            if isinstance(wide, pd.DataFrame) and not wide.empty:
                indicators = wide.copy()
                indicators["month"] = indicators["month"].astype(str).str[:7] + "-01"
                tables["indicators"] = indicators
                params["drivers"] = [{"name": column, "table": "indicators", "value": column, "date": "month",
                                      "agg": "sum" if column.startswith("spend_") or column == "sessions" else "mean",
                                      **({"expected_sign": sign} if (sign := indicator_sign(column, metric)) else {})}
                                     for column in indicators.columns if column not in ("month", metric)]  # never the outcome itself
                params["grain"] = "month"
        if "treated_from" in bind:
            drill = ctx.reports.get(bind["treated_from"])
            treated = None
            if drill is not None:
                try:
                    treated = next(row[1] for row in drill.table("drill_down").rows if row[0] == params["specificity"]["dimension"])
                except (KeyError, StopIteration):
                    treated = None
            if treated is None:
                params.pop("specificity", None)
            else:
                params["specificity"] = {**params["specificity"], "treated": [str(treated).split(" / ")[0]]}
        data = _engine_data(ctx, step, tables)
        run = engines.run_step(step.model_copy(update={"params": params}), data)
        if window_note:
            return EngineRun(run.result, run.report.model_copy(update={"assumptions": (window_note, *run.report.assumptions)}))
        return run

    if tool == "python.impact":
        if "anomaly_from" in bind:
            anomaly = ctx.results.get(bind["anomaly_from"])
            result = anomaly.analyst_output.result if anomaly is not None and anomaly.analyst_output is not None else None
            if result is None:
                return fail("The anomaly step produced no expected baseline to size against.")
            measurements = pd.DataFrame({"baseline": [float(result.expected)], "current": [float(result.actual)]})
            data = _engine_data(ctx, step, {"measurements": measurements})
            return engines.run_step(step.model_copy(update={"params": params}), data)
        if frame is None or frame.empty:
            return fail("The upstream series step returned no rows.")
        series = _series_frame(frame, metric)
        if "dimension_value" in frame.columns:
            series = series.groupby("month", as_index=False).sum(numeric_only=True)
        current, baseline = Period.model_validate(bind["current"]), Period.model_validate(bind["baseline"])
        months = pd.to_datetime(series["month"])
        label = pd.Series(None, index=series.index, dtype=object)
        label[(months >= pd.Timestamp(current.start)) & (months < pd.Timestamp(current.end))] = "current"
        label[(months >= pd.Timestamp(baseline.start)) & (months < pd.Timestamp(baseline.end))] = "baseline"
        measurements = pd.DataFrame({"period": label, "value": series["value"]}).dropna()
        if params.get("metric") in {"aov", "review_score", "cancellation_rate", "conversion_rate", "stockout_rate", "return_rate", "margin"}:
            params["aggregation"] = "mean"
        tables = {"measurements": measurements}
        if "targets_from" in bind and bind["targets_from"] in ctx.frames:
            targets = ctx.frames[bind["targets_from"]].get("rows")
            if isinstance(targets, pd.DataFrame) and not targets.empty:
                tables["targets"] = targets[["revenue_target"]]
        data = _engine_data(ctx, step, tables)
        return engines.run_step(step.model_copy(update={"params": params}), data)

    if tool == "python.scenario":
        if bind.get("unsupported") is not None and "panel_from" not in bind:
            described = "; ".join(item.get("source_phrase", "") for item in bind["unsupported"]) or "the stated change"
            return fail(f"Only price-change scenarios have a fitted response in this build (a demand elasticity fitted from past prices). "
                        f"'{described}' has no fitted relationship to perturb, so no figure is invented.")
        panel = ctx.frames.get(bind.get("panel_from", ""), {})
        if "sales" not in panel:
            return fail("The price panel step returned no rows.")
        tables = {"sales": panel["sales"], "competitor": panel["competitor"]}
        baseline = ctx.results.get(bind.get("baseline_from", ""))
        if baseline is not None and baseline.analyst_output is not None and baseline.analyst_output.result is not None:
            tables["baseline"] = pd.DataFrame({"revenue": [float(baseline.analyst_output.result.current)]})
        data = _engine_data(ctx, step, tables)
        return engines.run_step(step.model_copy(update={"params": params}), data)

    if tool == "python.segment":
        mode = params.get("mode")
        if mode == "segments":
            if frame is None or frame.empty:
                return fail("No customer feature rows were returned.")
            data = _engine_data(ctx, step, {params.get("entity", "customers"):
                                            table_from_frame(frame, query_id=_query_ids(ctx, step)[0], roles={params.get("key", "customer_unique_id"): "key"})})
            return engines.run_step(step.model_copy(update={"params": params}), data)
        if mode == "reorder":
            if frame is None or frame.empty:
                return fail("No reorder items were returned.")
            shortfall = ((frame["forecast_demand"] - frame["stock_on_hand"]).clip(lower=0) * frame["unit_cost"]).sum()
            share = float(bind.get("budget_share", 0.5))
            if shortfall <= 0:
                return fail("Every category already covers its forecast demand; there is nothing to reorder.")
            params["budget"] = float(shortfall) * share
            data = _engine_data(ctx, step, {"items": frame})
            run = engines.run_step(step.model_copy(update={"params": params}), data)
            note = f"The reorder budget was set to {int(share * 100)}% of the cost of covering every forecast gap."
            return EngineRun(run.result, run.report.model_copy(update={"assumptions": (note, *run.report.assumptions)}))
        actions = _actions_table(ctx, step, bind.get("actions_from", []))
        if actions is None:
            return fail("No quantified upstream finding is available to rank actions against.")
        grades = tuple(int(value) for value in actions["evidence_grade"])
        params["evidence_grades"] = grades
        data = _engine_data(ctx, step, {"actions": table_from_frame(actions, query_id=_query_ids(ctx, step)[0], roles={"action_id": "key"})})
        return engines.run_step(step.model_copy(update={"params": params}), data)
    return fail(f"No binding exists for {tool}.")


def _actions_table(ctx: StepContext, step: PlanStep, sources: list[str]) -> pd.DataFrame | None:
    """Candidate actions from the action library, sized by upstream engine figures only."""
    driver_name, driver_effect, driver_grade, metric = None, None, 1, "the metric"
    segments: list[tuple[str, float]] = []
    for source in sources:
        report = ctx.reports.get(source)
        result = ctx.results.get(source)
        if report is None:
            continue
        if report.engine == "diagnostic":
            metric = result.analyst_output.result.metric if result and result.analyst_output and result.analyst_output.result else metric
            ranked = report.table("ranked_drivers").rows if any(t.name == "ranked_drivers" for t in report.tables) else ()
            for row in ranked:
                if row[1] == "correlation" and row[7] >= 2 and driver_name is None:
                    driver_name, driver_grade = str(row[0]), int(row[7])
                if row[1] == "contribution" and len(segments) < 2:
                    segments.append((str(row[0]), float(row[2])))
        if report.engine == "impact":
            try:
                driver_effect = report.number("delta")
            except KeyError:
                pass
        if report.engine == "analytical_table" and any(t.name == "anomalies" for t in report.tables):
            for row in report.table("anomalies").rows[:2]:
                if row[6] is not None:
                    segments.append((f"{row[0]} {str(row[1])[:7]}" + (f" {row[3]}" if row[3] else ""), float(row[6])))
                    metric = str(row[0])
    candidates = []
    effect = driver_effect if driver_effect is not None else (segments[0][1] if segments else None)
    if driver_name is not None and effect is not None:
        candidates.append(("restore_driver", driver_name, abs(effect), driver_grade))
    for subject, value in segments[:2]:
        candidates.append(("focus_segment", subject, abs(value), 1 if driver_name is None else driver_grade))
    if not candidates:
        return None
    rows = []
    for index, (action_id, subject, impact, grade) in enumerate(candidates, start=1):
        template = next(item for item in ACTION_LIBRARY if item[0] == action_id)
        fill = lambda text, subject=subject: text.format(driver=subject, segment=subject, metric=metric)
        rows.append((f"{action_id}_{index}", fill(template[1]), impact, 1.0, grade, template[2], fill(template[3]), fill(template[4]),
                     fill(template[5]), fill(template[6]), fill(template[7])))
    # REC-4: when evidence is weak, the cheapest information-gathering options are what gets ranked.
    for action_id in ("gather_evidence", "monitor_metric"):
        template = next(item for item in ACTION_LIBRARY if item[0] == action_id)
        fill = lambda text: text.format(metric=metric, driver=metric, segment=metric)
        rows.append((action_id, fill(template[1]), 0.0, 1.0 if action_id == "gather_evidence" else 0.5, 1, template[2], fill(template[3]),
                     fill(template[4]), fill(template[5]), fill(template[6]), fill(template[7])))
    return pd.DataFrame(rows, columns=["action_id", "title", "expected_impact", "cost", "evidence_grade", "kind", "assumptions",
                                       "trade_offs", "sensitivity", "monitor", "data_that_would_change_ranking"])


TOOL_HANDLERS: Mapping[str, Callable[[PlanStep, StepContext], EngineRun]] = {
    "sql": _sql,
    "analytical_table": _analytical,
    "catalog": _catalog,
    "python.anomaly": _engine,
    "python.driver": _engine,
    "python.forecast": _engine,
    "python.impact": _engine,
    "python.scenario": _engine,
    "python.segment": _engine,
}


def run_tool(step: PlanStep, ctx: StepContext) -> EngineRun:
    handler = TOOL_HANDLERS.get(step.tool)
    if handler is None:  # pragma: no cover - PlanStep.tool is a closed literal
        raise ValueError(f"unknown tool {step.tool!r}")
    return handler(step, ctx)


__all__ = ["ACTION_LIBRARY", "ANALYTICAL_TABLES", "DATASET_TABLES", "TOOL_HANDLERS", "StepContext", "Warehouse", "run_tool"]
