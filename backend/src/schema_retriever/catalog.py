"""Small, read-only schema catalog used for grounding and value linking.

The catalog keeps table names, profiled columns and low-cardinality literal
values. It deliberately samples values instead of exposing full tables, and it
skips identifiers, free text, sensitive columns and continuous measures.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from contracts.models import ContractModel
from gateway.connection import ConnectionManager
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

_SENSITIVE_PARTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "ssn",
    "social_security",
    "credit_card",
    "card_number",
    "cvv",
    "email",
    "phone",
)

_FREE_TEXT_PARTS = (
    "comment",
    "message",
    "description",
    "title",
    "body",
    "review_text",
)

_MEASURE_PARTS = (
    "price",
    "value",
    "freight",
    "weight",
    "length",
    "lenght",
    "height",
    "width",
    "latitude",
    "longitude",
    "lat",
    "lng",
    "amount",
    "revenue",
    "cost",
    "total",
)

_TEXT_TYPE_PARTS = ("CHAR", "TEXT", "STRING", "CLOB")
_NUMERIC_TYPE_PARTS = ("INT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE", "REAL")
_TEMPORAL_TYPE_PARTS = ("DATE", "TIME")

_CATALOG_FORMAT = "schema-catalog-v1"


class CatalogColumn(ContractModel):
    name: str
    data_type: str
    values: tuple[str, ...] = ()


class CatalogForeignKey(ContractModel):
    """A database-declared relationship; inferred name matches are not proof."""

    columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]


class CatalogTable(ContractModel):
    name: str
    columns: tuple[CatalogColumn, ...] = ()
    foreign_keys: tuple[CatalogForeignKey, ...] = ()
    unique_keys: tuple[tuple[str, ...], ...] = ()


class SchemaCatalog(ContractModel):
    version: str
    tables: tuple[CatalogTable, ...] = ()

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(table.name for table in self.tables)

    @property
    def domains(self) -> tuple[str, ...]:
        return tuple(sorted({_humanize(table.name) for table in self.tables}))

    def get_table(self, name: str) -> CatalogTable | None:
        lowered = name.lower()
        return next(
            (table for table in self.tables if table.name.lower() == lowered),
            None,
        )

    def get_tables(self, names: Iterable[str]) -> tuple[CatalogTable, ...]:
        requested = list(dict.fromkeys(names))
        found: list[CatalogTable] = []
        for name in requested:
            table = self.get_table(name)
            if table is not None:
                found.append(table)
        return tuple(found)

    def get_column(self, table: str, column: str) -> CatalogColumn | None:
        table_entry = self.get_table(table)
        if table_entry is None:
            return None
        lowered = column.lower()
        return next(
            (entry for entry in table_entry.columns if entry.name.lower() == lowered),
            None,
        )

    @classmethod
    def from_manager(
        cls,
        manager: ConnectionManager,
        *,
        max_cardinality: int = 500,
    ) -> SchemaCatalog:
        if max_cardinality < 1:
            raise ValueError("max_cardinality must be at least 1")

        inspector = sqlalchemy_inspect(manager.engine)
        table_names = sorted(inspector.get_table_names())
        tables: list[CatalogTable] = []

        with manager.connect() as connection:
            for table_name in table_names:
                columns: list[CatalogColumn] = []
                for column in inspector.get_columns(table_name):
                    name = str(column["name"])
                    data_type = str(column["type"])
                    values: tuple[str, ...] = ()
                    if _is_profileable(name, data_type):
                        values = _distinct_values(
                            connection,
                            table_name,
                            name,
                            max_cardinality,
                        )
                    columns.append(
                        CatalogColumn(
                            name=name,
                            data_type=data_type,
                            values=values,
                        )
                    )
                foreign_keys = tuple(
                    CatalogForeignKey(
                        columns=tuple(item.get("constrained_columns") or ()),
                        referred_table=str(item["referred_table"]),
                        referred_columns=tuple(item.get("referred_columns") or ()),
                    )
                    for item in inspector.get_foreign_keys(table_name)
                    if item.get("constrained_columns")
                    and item.get("referred_table")
                    and item.get("referred_columns")
                )
                primary = inspector.get_pk_constraint(table_name)
                unique_keys = {
                    tuple(item.get("constrained_columns") or ())
                    for item in (primary,)
                    if item.get("constrained_columns")
                }
                unique_keys.update(
                    tuple(item.get("column_names") or ())
                    for item in inspector.get_unique_constraints(table_name)
                    if item.get("column_names")
                )
                unique_keys.discard(())
                tables.append(
                    CatalogTable(
                        name=table_name,
                        columns=tuple(columns),
                        foreign_keys=foreign_keys,
                        unique_keys=tuple(sorted(unique_keys)),
                    )
                )

        entries = tuple(tables)
        return cls(version=_catalog_version(entries), tables=entries)


@dataclass(frozen=True, slots=True)
class JoinEdge:
    """A declared or inferred relationship between two catalog tables."""

    left_table: str
    left_column: str
    right_table: str
    right_column: str
    column_pairs: tuple[tuple[str, str], ...] = ()
    status: str = "proposed"

    def __post_init__(self) -> None:
        if not self.column_pairs:
            object.__setattr__(
                self, "column_pairs", ((self.left_column, self.right_column),)
            )
        if self.status not in {"approved", "proposed"}:
            raise ValueError("join status must be 'approved' or 'proposed'")

    @property
    def edge_id(self) -> str:
        parts = []
        for left_column, right_column in self.column_pairs:
            left = (self.left_table.lower(), left_column.lower())
            right = (self.right_table.lower(), right_column.lower())
            if right < left:
                left, right = right, left
            parts.append(f"{left[0]}.{left[1]}={right[0]}.{right[1]}")
        return "&".join(sorted(parts))

    def other_table(self, table: str) -> str:
        lowered = table.lower()
        if self.left_table.lower() == lowered:
            return self.right_table
        if self.right_table.lower() == lowered:
            return self.left_table
        raise ValueError(f"{table!r} is not part of edge {self.edge_id}")

    def columns_for(self, table: str) -> tuple[str, str]:
        lowered = table.lower()
        if self.left_table.lower() == lowered:
            return self.left_table, self.left_column
        if self.right_table.lower() == lowered:
            return self.right_table, self.right_column
        raise ValueError(f"{table!r} is not part of edge {self.edge_id}")


_GOVERNED_APPROVED_EDGES: frozenset[str] = frozenset(
    {
        "order_items.order_id=orders.order_id",
        "order_payments.order_id=orders.order_id",
        "customers.customer_id=orders.customer_id",
        "order_items.product_id=products.product_id",
        "order_reviews.order_id=orders.order_id",
        "order_items.seller_id=sellers.seller_id",
    }
)


@dataclass(frozen=True, slots=True)
class JoinGraph:
    """Deterministic join paths over shared ID columns in the catalog."""

    edges: tuple[JoinEdge, ...] = ()

    @classmethod
    def from_catalog(
        cls,
        catalog: SchemaCatalog,
        *,
        approved_edges: Iterable[str] | None = None,
    ) -> JoinGraph:
        tables = catalog.tables
        edges: list[JoinEdge] = []
        approved_set = _GOVERNED_APPROVED_EDGES | frozenset(approved_edges or ())
        table_by_name = {table.name.lower(): table for table in tables}
        for table in tables:
            for foreign_key in table.foreign_keys:
                if not foreign_key.columns or len(foreign_key.columns) != len(
                    foreign_key.referred_columns
                ):
                    continue
                referred = table_by_name.get(foreign_key.referred_table.lower())
                if referred is None:
                    continue
                edges.append(
                    JoinEdge(
                        left_table=table.name,
                        left_column=foreign_key.columns[0],
                        right_table=referred.name,
                        right_column=foreign_key.referred_columns[0],
                        column_pairs=tuple(
                            zip(foreign_key.columns, foreign_key.referred_columns)
                        ),
                        status="approved",
                    )
                )
        for index, left in enumerate(tables):
            left_columns = {column.name.lower(): column.name for column in left.columns}
            for right in tables[index + 1 :]:
                right_columns = {
                    column.name.lower(): column.name for column in right.columns
                }
                candidates = sorted(
                    name
                    for name in set(left_columns) & set(right_columns)
                    if name == "id" or name.endswith("_id")
                )
                if not candidates:
                    continue
                if any(
                    {edge.left_table.lower(), edge.right_table.lower()}
                    == {left.name.lower(), right.name.lower()}
                    for edge in edges
                ):
                    continue
                column = candidates[0]
                temp_edge = JoinEdge(
                    left_table=left.name,
                    left_column=left_columns[column],
                    right_table=right.name,
                    right_column=right_columns[column],
                    status="proposed",
                )
                edge_status = (
                    "approved" if temp_edge.edge_id in approved_set else "proposed"
                )
                edges.append(
                    JoinEdge(
                        left_table=left.name,
                        left_column=left_columns[column],
                        right_table=right.name,
                        right_column=right_columns[column],
                        status=edge_status,
                    )
                )
        edges.sort(key=lambda edge: edge.edge_id)
        return cls(edges=tuple(edges))

    def find_path(self, start: str, end: str) -> tuple[JoinEdge, ...] | None:
        start_key = start.lower()
        end_key = end.lower()
        if start_key == end_key:
            return ()
        if start_key not in self._adjacency() or end_key not in self._adjacency():
            return None

        queue: deque[tuple[str, tuple[JoinEdge, ...]]] = deque([(start_key, ())])
        visited = {start_key}
        adjacency = self._adjacency()

        while queue:
            table, path = queue.popleft()
            for neighbour, edge in adjacency.get(table, ()):
                if neighbour in visited:
                    continue
                next_path = path + (edge,)
                if neighbour == end_key:
                    return next_path
                visited.add(neighbour)
                queue.append((neighbour, next_path))
        return None

    def neighbors(self, table: str) -> tuple[tuple[str, JoinEdge], ...]:
        return self._adjacency().get(table.lower(), ())

    def edge_between(self, left: str, right: str) -> JoinEdge | None:
        lowered = (left.lower(), right.lower())
        for edge in self.edges:
            if edge.status != "approved":
                continue
            if {
                edge.left_table.lower(),
                edge.right_table.lower(),
            } == set(lowered):
                return edge
        return None

    def _adjacency(self) -> dict[str, tuple[tuple[str, JoinEdge], ...]]:
        neighbors: dict[str, list[tuple[str, JoinEdge]]] = {}
        for edge in self.edges:
            if edge.status != "approved":
                continue
            left = edge.left_table.lower()
            right = edge.right_table.lower()
            neighbors.setdefault(left, []).append((right, edge))
            neighbors.setdefault(right, []).append((left, edge))

        return {
            table: tuple(sorted(items, key=lambda item: (item[0], item[1].edge_id)))
            for table, items in neighbors.items()
        }


def _humanize(name: str) -> str:
    return name.replace("_", " ").strip().lower()


def _is_sensitive(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in _SENSITIVE_PARTS)


def _is_identifier(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered == "id"
        or lowered.endswith("_id")
        or "zip_code" in lowered
        or "sequential" in lowered
    )


def _is_temporal_name(name: str) -> bool:
    lowered = name.lower()
    parts = set(lowered.split("_"))
    return bool(parts & {"date", "time", "timestamp"}) or lowered.endswith("_at")


def _is_free_text(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in _FREE_TEXT_PARTS)


def _is_measure(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in _MEASURE_PARTS)


def _is_profileable(name: str, data_type: str) -> bool:
    if (
        _is_sensitive(name)
        or _is_identifier(name)
        or _is_free_text(name)
        or _is_temporal_name(name)
    ):
        return False

    upper_type = data_type.upper()
    if any(part in upper_type for part in _TEMPORAL_TYPE_PARTS):
        return False
    if any(part in upper_type for part in _TEXT_TYPE_PARTS):
        return True
    if any(part in upper_type for part in _NUMERIC_TYPE_PARTS):
        return not _is_measure(name)
    return False


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _distinct_values(
    connection: Connection,
    table: str,
    column: str,
    max_cardinality: int,
) -> tuple[str, ...]:
    query = (
        f"SELECT DISTINCT {_quote(column)} "
        f"FROM {_quote(table)} "
        f"WHERE {_quote(column)} IS NOT NULL "
        f"LIMIT {max_cardinality + 1}"
    )
    try:
        rows = connection.exec_driver_sql(query).all()
    except SQLAlchemyError:
        return ()

    values: dict[str, str] = {}
    for row in rows:
        value = str(row[0]).strip()
        if not value or len(value) > 120:
            continue
        values.setdefault(value.casefold(), value)

    if len(values) > max_cardinality:
        return ()
    return tuple(sorted(values.values(), key=str.casefold))


def _catalog_version(tables: tuple[CatalogTable, ...]) -> str:
    payload = {
        "format": _CATALOG_FORMAT,
        "tables": [
            {
                "name": table.name,
                "columns": [
                    {
                        "name": column.name,
                        "type": column.data_type,
                        "values": list(column.values),
                    }
                    for column in table.columns
                ],
            }
            for table in tables
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


__all__ = [
    "CatalogColumn",
    "CatalogTable",
    "JoinEdge",
    "JoinGraph",
    "SchemaCatalog",
]
