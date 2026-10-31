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

import re
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


# --------------------------------------------------------------------------- #
# Track 4: one table, the metric list, and example questions. Same rules as
# above: catalog facts plus fixed COUNT / MIN / MAX / PRAGMA statements over
# identifiers from the closed registry. No SQL is generated from user text.
# --------------------------------------------------------------------------- #

_TABLE_CUE = re.compile(
    r"\btables?\b|\bcolumns?\b|\bschema\b|\bfields?\b|\bwhat(?:'s| is| does)\s+(?:in|inside)\b|\bwhat(?:'s| is)\s+in\b|"
    r"\bdescribe\b|\binside\b|\bcontains?\b|\bstructure of\b",
    re.IGNORECASE,
)
_METRIC_LIST = re.compile(
    r"\b(?:which|what) (?:metrics|kpis|measures)\b|\bmetrics (?:can|could|do) (?:i|you|we)\b|\blist (?:the |all |your )?(?:metrics|kpis)\b|"
    r"\bwhat can i ask\b|\bwhat (?:can|could) you (?:calculate|measure|compute)\b",
    re.IGNORECASE,
)
_DIMENSION_WORDS = {"product_category": "category", "customer_state": "state", "payment_type": "payment type",
                    "order_status": "order status", "customer_city": "city", "seller_state": "seller state"}


def table_mentioned(question: str, registry: TableRegistry | None = None) -> str | None:
    """The registered table a question asks *about* ("what is in order_items?"), if any.

    A table name alone is not enough - "orders" and "customers" are ordinary
    words - so a structural cue (table, columns, describe, what is in ...) is
    required too. Only names from the closed registry can match.
    """
    if not _TABLE_CUE.search(question):
        return None
    registry = registry or TableRegistry.default()
    text = question.lower()
    for table in sorted(registry.tables, key=lambda item: len(item.name), reverse=True):
        spaced = table.name.replace("_", " ")
        if re.search(rf"\b(?:{re.escape(table.name)}|{re.escape(spaced)})\b", text):
            return table.name
    return None


def asks_for_metric_list(question: str) -> bool:
    return bool(_METRIC_LIST.search(question))


def example_questions(metric_id: str) -> tuple[str, ...]:
    """Questions the agent can answer about a metric. Digit-free, so they carry no figure."""
    metric = all_metrics().get(metric_id)
    if metric is None:
        return ()
    label = metric.name if metric.name.isupper() else metric.name.lower()
    questions = [f"What was {label} last month?", f"How does {label} trend look today?"]
    dimensions = [d.name for d in metric.allowed_dimensions]
    split = next((name for name in ("product_category", "customer_state", "payment_type", "order_status") if name in dimensions), None)
    if split is not None:
        questions.append(f"What was {label} by {_DIMENSION_WORDS[split]} last month?")
    questions.append(f"Why did {label} change last month?")
    return tuple(questions)


class ColumnFact(ContractModel):
    name: str
    data_type: str


class TableDetail(ContractModel):
    table: TableFact
    key_columns: tuple[str, ...]
    columns: tuple[ColumnFact, ...]
    metrics: tuple[str, ...]
    example_questions: tuple[str, ...]


def describe_table(connection: Connection, name: str, registry: TableRegistry | None = None) -> TableDetail | None:
    """One table from the catalog: layer, grain, row count, date span, columns, the metrics built on it."""
    registry = registry or TableRegistry.default()
    info = registry.get(name)
    if info is None:
        return None
    present = name in _present(connection)
    count = low = high = None
    columns: tuple[ColumnFact, ...] = ()
    if present:
        # Identifiers come from the closed registry, never from user text.
        (count,) = connection.execute(text(f'SELECT COUNT(*) FROM "{info.name}"')).one()
        if info.date_column:
            low, high = connection.execute(
                text(f'SELECT MIN("{info.date_column}"), MAX("{info.date_column}") FROM "{info.name}"')
            ).one()
        columns = tuple(ColumnFact(name=str(row[1]), data_type=str(row[2] or "")) for row in
                        connection.execute(text(f'PRAGMA table_info("{info.name}")')).all())
    fact = TableFact(
        name=info.name, subject=info.subject, layer=_layer(info), grain=info.grain, description=info.description,
        present=present, row_count=None if count is None else int(count), date_column=info.date_column,
        date_min=None if low is None else str(low)[:10], date_max=None if high is None else str(high)[:10],
    )
    metrics = tuple(metric.metric_id for metric in all_metrics().metrics if metric.base_table == info.name)
    examples = tuple(dict.fromkeys(question for metric_id in metrics[:2] for question in example_questions(metric_id)[:2]))
    return TableDetail(table=fact, key_columns=info.key_columns, columns=columns, metrics=metrics,
                       example_questions=examples or ("What data do you have?", "Which metrics can I ask about?"))


__all__ = [
    "ColumnFact",
    "MetricFact",
    "TableDetail",
    "TableFact",
    "WarehouseDescription",
    "asks_for_metric_list",
    "catalog_facts",
    "describe_table",
    "describe_warehouse",
    "example_questions",
    "render_answer",
    "table_mentioned",
]
