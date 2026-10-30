"""Catalog-backed answer to "what data do you have?" (scope.md D1, acceptance 1.13/1.16).

Every figure in the answer is either a catalog fact (names, grains,
aggregation classes, synthetic labels) or a count / date bound read from the
warehouse by a fixed SQL statement. No model writes any part of it (SAFE-8),
and every synthetic table and metric is labelled as such (V2-SYN-4).

:func:`describe_warehouse` returns the facts; :func:`catalog_facts` packs
them into the V2 ``CatalogFactsPayload``; :func:`render_answer` turns them
into the deterministic markdown answer.
"""

from __future__ import annotations

from typing import Literal

from contracts.models import ContractModel
from contracts.v2 import CatalogFact, CatalogFactsPayload
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.engine import Connection

from semantic.aggregation import AggregationRegistry
from semantic.metrics_v2 import all_metrics, is_synthetic_metric
from semantic.tables import TableInfo, TableRegistry
from semantic.versioning import catalog_version

Layer = Literal["real", "synthetic", "user_supplied", "analytical"]

_SUBJECT_ORDER = (
    "orders", "customers", "products", "sellers", "geography",
    "marketing", "pricing", "operations", "targets", "user_data", "analytics",
)


class TableFact(ContractModel):
    name: str
    subject: str
    layer: Layer
    grain: str
    description: str
    present: bool
    row_count: int | None = Field(default=None, ge=0)
    date_column: str | None = None
    date_min: str | None = None
    date_max: str | None = None


class MetricFact(ContractModel):
    metric_id: str
    name: str
    aggregation: str
    is_synthetic: bool
    base_table: str
    dimensions: tuple[str, ...]


class WarehouseDescription(ContractModel):
    catalog_version: str
    tables: tuple[TableFact, ...]
    metrics: tuple[MetricFact, ...]

    @property
    def synthetic_tables(self) -> tuple[str, ...]:
        return tuple(t.name for t in self.tables if t.layer == "synthetic" and t.present)


def _layer(table: TableInfo) -> Layer:
    if table.is_synthetic:
        return "synthetic"
    return {"user_supplied": "user_supplied", "analytical": "analytical"}.get(table.source, "real")


def _present(connection: Connection) -> set[str]:
    rows = connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).all()
    return {row[0] for row in rows}


def describe_warehouse(connection: Connection, registry: TableRegistry | None = None) -> WarehouseDescription:
    registry = registry or TableRegistry.default()
    present = _present(connection)
    tables = []
    for table in registry.tables:
        if table.name not in present:
            tables.append(TableFact(
                name=table.name, subject=table.subject, layer=_layer(table), grain=table.grain,
                description=table.description, present=False, date_column=table.date_column,
            ))
            continue
        # Identifiers come from the closed registry, never from user text.
        (count,) = connection.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).one()
        low = high = None
        if table.date_column:
            low, high = connection.execute(
                text(f'SELECT MIN("{table.date_column}"), MAX("{table.date_column}") FROM "{table.name}"')
            ).one()
        tables.append(TableFact(
            name=table.name, subject=table.subject, layer=_layer(table), grain=table.grain,
            description=table.description, present=True, row_count=int(count),
            date_column=table.date_column,
            date_min=None if low is None else str(low)[:10],
            date_max=None if high is None else str(high)[:10],
        ))
    tables.sort(key=lambda t: (_SUBJECT_ORDER.index(t.subject) if t.subject in _SUBJECT_ORDER else 99, t.name))

    aggregations = AggregationRegistry()
    metrics = tuple(
        MetricFact(
            metric_id=metric.metric_id,
            name=metric.name,
            aggregation=aggregations.require(metric.metric_id).aggregation,
            is_synthetic=is_synthetic_metric(metric.metric_id),
            base_table=metric.base_table,
            dimensions=tuple(d.name for d in metric.allowed_dimensions),
        )
        for metric in all_metrics().metrics
    )
    return WarehouseDescription(catalog_version=catalog_version(registry), tables=tuple(tables), metrics=metrics)


def catalog_facts(description: WarehouseDescription) -> CatalogFactsPayload:
    facts: list[CatalogFact] = []
    for table in description.tables:
        facts.append(CatalogFact(key=f"table.{table.name}.layer", value=table.layer, source="catalog"))
        if table.present:
            facts.append(CatalogFact(key=f"table.{table.name}.row_count", value=table.row_count, source="sql"))
            if table.date_min:
                facts.append(CatalogFact(key=f"table.{table.name}.date_range", value=[table.date_min, table.date_max], source="sql"))
    for metric in description.metrics:
        facts.append(CatalogFact(
            key=f"metric.{metric.metric_id}",
            value={"aggregation": metric.aggregation, "is_synthetic": metric.is_synthetic},
            source="catalog",
        ))
    return CatalogFactsPayload(catalog_version=description.catalog_version, facts=tuple(facts))


_LAYER_LABEL = {
    "real": "real (Olist snapshot)",
    "synthetic": "**synthetic**",
    "user_supplied": "user-supplied",
    "analytical": "derived (engine output)",
}


def render_answer(description: WarehouseDescription) -> str:
    """The deterministic markdown answer to "what data do you have?"."""
    base = [t for t in description.tables if t.present and t.layer != "analytical"]
    synthetic = [t for t in base if t.layer == "synthetic"]
    lines = [
        (f"The warehouse holds **{len(base)} tables**: "
        f"{len(base) - len(synthetic)} real or user-supplied and {len(synthetic)} synthetic."),
        "",
    ]
    if synthetic:
        lines += [
            "Synthetic tables are generated for demonstration and are **not "
            "measurements of the real business**: "
            + ", ".join(f"`{t.name}`" for t in synthetic) + ".",
            "",
        ]
    lines += ["| Table | Subject | Layer | Grain | Rows | Dates |", "| --- | --- | --- | --- | --- | --- |"]
    for table in description.tables:
        if not table.present:
            continue
        dates = f"{table.date_min} to {table.date_max}" if table.date_min else "-"
        lines.append(
            f"| `{table.name}` | {table.subject} | {_LAYER_LABEL[table.layer]} | {table.grain} "
            f"| {table.row_count:,} | {dates} |"
        )
    missing = [t.name for t in description.tables if not t.present and t.layer != "analytical"]
    if missing:
        lines += ["", "Registered but not loaded in this database: " + ", ".join(f"`{n}`" for n in missing) + "."]
    lines += [
        "",
        f"**{len(description.metrics)} metrics** can be calculated:",
        "",
        "| Metric | Aggregation | Layer | Dimensions |",
        "| --- | --- | --- | --- |",
    ]
    for metric in description.metrics:
        layer = "**synthetic**" if metric.is_synthetic else "real"
        lines.append(f"| `{metric.metric_id}` ({metric.name}) | {metric.aggregation} | {layer} | {', '.join(metric.dimensions) or '-'} |")
    lines += [
        "",
        ("Real order data runs to 2018-10, but 2018-09 and 2018-10 are incomplete "
        "collection months; the last complete month is reported per metric by the "
        "completeness rule."),
        "",
        f"Catalog version `{description.catalog_version}`.",
    ]
    return "\n".join(lines) + "\n"


__all__ = ["MetricFact", "TableFact", "WarehouseDescription", "catalog_facts", "describe_warehouse", "render_answer"]
