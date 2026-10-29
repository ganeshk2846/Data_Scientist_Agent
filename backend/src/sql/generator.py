"""Deterministic NL2SQL generation with CTE skeletons (SQL-1, SQL-5, SQL-16).

The generator is intentionally model-free. It grounds the question against the
retrieved catalog, selects a measure and optional grouping dimension, plans
joins from catalog-inferred edges, and emits one candidate whose every table and
column is recorded in a frozen :class:`SchemaAllowlist`.

For multi-table questions it builds one CTE per table first and only then fills
the join predicates. The repair loop (``repairer.py``) consumes the allowlist
unchanged, so generation and repair cannot see a wider schema than retrieval
approved.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from dataclasses import dataclass
from typing import Iterable

from contracts.models import (
    AllowlistedColumn,
    ColumnRole,
    IntendedColumn,
    LinkedValue,
    SchemaAllowlist,
    SqlCandidate,
)
from schema_retriever.catalog import (
    CatalogColumn,
    CatalogTable,
    JoinEdge,
    JoinGraph,
    SchemaCatalog,
)

_STOPWORDS = frozenset(
    """
    a an and any are as at average be been being by can could did do does each
    for from get give go had has have how i if in into is it its many me most
    much my number of on or our per please record records row rows show sum
    table tables tell that the their them then there these they this those to
    top total up us was we were what when where which who why will with would
    you your
    """.split()
)

_TABLE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("orders", ("order", "orders")),
    ("order_items", ("order item", "order items", "line item", "line items")),
    ("order_payments", ("payment", "payments")),
    ("order_reviews", ("review", "reviews", "rating", "ratings")),
    ("customers", ("customer", "customers", "buyer", "buyers")),
    ("products", ("product", "products")),
    ("sellers", ("seller", "sellers")),
)

_COUNT_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("order_items", ("order item", "order items", "line item", "line items")),
    ("orders", ("order", "orders")),
    ("order_reviews", ("review", "reviews", "rating", "ratings")),
    ("order_payments", ("payment", "payments")),
    ("customers", ("customer", "customers", "buyer", "buyers")),
    ("products", ("product", "products")),
    ("sellers", ("seller", "sellers")),
)

_DIMENSION_RULES: tuple[tuple[tuple[str, ...], str, str, str, ColumnRole], ...] = (
    (("customer state", "customer states", "state", "states", "province"), "customers", "customer_state", "state", "dimension"),
    (("customer city", "customer cities", "city", "cities"), "customers", "customer_city", "city", "dimension"),
    (("order status", "order statuses", "status", "statuses"), "orders", "order_status", "status", "dimension"),
    (("payment type", "payment types", "payment method", "payment methods"), "order_payments", "payment_type", "payment_type", "dimension"),
    (("product category", "product categories", "category", "categories"), "products", "product_category_name", "category", "dimension"),
    (("seller", "sellers"), "sellers", "seller_id", "seller_id", "key"),
    (("product", "products"), "products", "product_id", "product_id", "key"),
    (("month", "monthly"), "orders", "order_purchase_timestamp", "month", "time"),
    (("year", "yearly"), "orders", "order_purchase_timestamp", "year", "time"),
)

_DIMENSION_EXPRESSION_KINDS = {
    "customer state": "column",
    "customer city": "column",
    "order status": "column",
    "payment type": "column",
    "product category": "column",
    "seller": "column",
    "product": "column",
    "month": "month",
    "year": "year",
}

_STATUS_WORDS = {
    "delivered": "delivered",
    "shipped": "shipped",
    "canceled": "canceled",
    "cancelled": "canceled",
    "processing": "processing",
    "invoiced": "invoiced",
    "approved": "approved",
    "unavailable": "unavailable",
}

_NUMERIC_TYPES = ("INT", "REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC")
_KEY_SUFFIXES = ("_id",)

_TOP_PATTERN = re.compile(r"\b(?:top|first|bottom|last)\s+(\d+)\b")
_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
_BY_PATTERN = re.compile(r"\b(?:by|per|for each|each)\s+([a-z0-9 ]+)")

_ALIAS_BASES = {
    "orders": "o",
    "order_items": "oi",
    "order_payments": "op",
    "order_reviews": "r",
    "customers": "c",
    "products": "p",
    "sellers": "s",
    "product_category_translation": "pct",
    "geolocation": "g",
}


class SQLGenerationError(ValueError):
    """A question cannot be grounded into a safe candidate."""

    def __init__(self, what_understood: str, what_needs_clarification: str) -> None:
        super().__init__(what_needs_clarification)
        self.what_understood = what_understood
        self.what_needs_clarification = what_needs_clarification


@dataclass(frozen=True, slots=True)
class GenerationResult:
    candidate: SqlCandidate
    allowlist: SchemaAllowlist
    question: str
    tables: tuple[str, ...]
    linked_values: tuple[LinkedValue, ...] = ()


@dataclass(frozen=True, slots=True)
class _Measure:
    table: str
    output: str
    role: ColumnRole
    template: str
    columns: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _Dimension:
    table: str
    column: str
    output: str
    role: ColumnRole
    kind: str


@dataclass(frozen=True, slots=True)
class _Filter:
    table: str
    column: str
    template: str


@dataclass(frozen=True, slots=True)
class _Selected:
    table: str
    output: str
    role: ColumnRole
    template: str
    columns: tuple[tuple[str, str], ...] = ()


def _normalize(text: str) -> str:
    lowered = text.lower().replace("&", " and ")
    lowered = re.sub(r"[_\-/]+", " ", lowered)
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    return " ".join(lowered.split())


def _contains(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _humanize(name: str) -> str:
    return name.replace("_", " ").strip().lower()


def _escape_literal(value: str) -> str:
    return value.replace("'", "''")


def _candidate_id(prefix: str, sql: str, dialect: str) -> str:
    digest = hashlib.sha256(f"{dialect}\n{sql}".encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:12]}"


class SQLGenerator:
    """Grounds a question to one safe, dialect-aware SQL candidate."""

    def __init__(
        self,
        catalog: SchemaCatalog,
        *,
        join_graph: JoinGraph | None = None,
        dialect: str = "sqlite",
        limit: int = 100,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self._catalog = catalog
        self._join_graph = join_graph or JoinGraph.from_catalog(catalog)
        self._dialect = dialect
        self._limit = limit

    @property
    def catalog(self) -> SchemaCatalog:
        return self._catalog

    @property
    def join_graph(self) -> JoinGraph:
        return self._join_graph

    def generate(
        self,
        question: str,
        *,
        linked_values: Iterable[LinkedValue] = (),
        icl_exemplars: Iterable[str] = (),
    ) -> GenerationResult:
        normalized = _normalize(question)
        if not normalized:
            raise ValueError("question must not be empty")

        linked = tuple(linked_values)
        mentioned = self._mentioned_tables(normalized)
        dimension = self._dimension(normalized)
        measure = self._measure(normalized, mentioned)
        filters, filter_tables = self._filters(normalized, linked)

        list_request = _contains(normalized, "list") or _contains(
            normalized, "show"
        ) or _contains(normalized, "find") or _contains(normalized, "display")

        if measure is None and dimension is not None and not list_request:
            measure = self._count_measure(normalized, mentioned | {dimension.table})
        if measure is None and dimension is None and list_request and mentioned:
            measure = None
        if measure is None and dimension is None and not list_request:
            raise SQLGenerationError(
                f"I understood the question as: {question}",
                "Name a table, metric, or grouping present in the catalog.",
            )

        required = set(mentioned)
        if measure is not None:
            required.add(measure.table)
        if dimension is not None:
            required.add(dimension.table)
        required.update(filter_tables)
        if not required:
            raise SQLGenerationError(
                f"I understood the question as: {question}",
                "I could not identify a table to query; please name one.",
            )

        missing = sorted(
            table for table in required if self._catalog.get_table(table) is None
        )
        if missing:
            raise SQLGenerationError(
                f"I understood the question as: {question}",
                f"The catalog does not contain: {', '.join(missing)}.",
            )

        base = (
            measure.table
            if measure is not None
            else dimension.table
            if dimension is not None
            else sorted(required)[0]
        )
        used_tables = self._used_tables(base, required)
        join_edges = self._join_plan(base, used_tables)
        if join_edges is None:
            raise SQLGenerationError(
                f"I understood the question as: {question}",
                "The requested tables have no approved join path in the catalog.",
            )

        ordered_tables = [base]
        for edge in join_edges:
            for table in (edge.left_table, edge.right_table):
                if table not in ordered_tables:
                    ordered_tables.append(table)
        aliases = self._assign_aliases(ordered_tables)

        filters = tuple(
            _Filter(
                table=item.table,
                column=item.column,
                template=item.template,
            )
            for item in filters
        )

        selected: list[_Selected] = []
        if dimension is not None:
            selected.append(
                _Selected(
                    table=dimension.table,
                    output=dimension.output,
                    role=dimension.role,
                    template=self._dimension_expression(
                        dimension, aliases[dimension.table]
                    ),
                    columns=((dimension.table, dimension.column),),
                )
            )
        if measure is not None:
            selected.append(
                _Selected(
                    table=measure.table,
                    output=measure.output,
                    role=measure.role,
                    template=measure.template.format(alias=aliases[measure.table]),
                    columns=measure.columns,
                )
            )
        if measure is None:
            selected.extend(
                self._list_columns(
                    base,
                    dimension,
                    aliases,
                )
            )

        if not selected:
            raise SQLGenerationError(
                f"I understood the question as: {question}",
                "I could not choose any columns to return.",
            )

        needed = self._needed_columns(
            used_tables, selected, filters, join_edges
        )
        allowlist = self._allowlist(used_tables, needed)
        sql = self._render(
            base=base,
            ordered_tables=ordered_tables,
            aliases=aliases,
            join_edges=join_edges,
            selected=selected,
            filters=filters,
            dimension=dimension,
            measure=measure,
            needed=needed,
            question=normalized,
        )

        candidate = SqlCandidate(
            candidate_id=_candidate_id("gen", sql, self._dialect),
            sql=sql,
            dialect=self._dialect,
            origin="generator",
            intended_columns=tuple(
                IntendedColumn(name=item.output, role=item.role)
                for item in selected
            ),
            grain=tuple(
                dict.fromkeys(
                    column
                    for item in selected
                    if item.role in ("dimension", "time")
                    for _, column in item.columns
                )
            ),
            uses_edges=tuple(edge.edge_id for edge in join_edges),
            icl_exemplars_used=tuple(icl_exemplars) or None,
        )
        return GenerationResult(
            candidate=candidate,
            allowlist=allowlist,
            question=question,
            tables=tuple(ordered_tables),
            linked_values=linked,
        )

    def _mentioned_tables(self, question: str) -> set[str]:
        return {
            table
            for table, phrases in _TABLE_ALIASES
            if self._catalog.get_table(table) is not None
            and any(_contains(question, phrase) for phrase in phrases)
        }

    def _dimension(self, question: str) -> _Dimension | None:
        for phrases, table, column, output, role in _DIMENSION_RULES:
            if not any(_contains(question, phrase) for phrase in phrases):
                continue
            if self._catalog.get_table(table) is None:
                continue
            if self._catalog.get_column(table, column) is None:
                continue
            kind = _DIMENSION_EXPRESSION_KINDS.get(phrases[0], "column")
            return _Dimension(
                table=table,
                column=column,
                output=output,
                role=role,
                kind=kind,
            )
        return self._generic_dimension(question)

    def _generic_dimension(self, question: str) -> _Dimension | None:
        match = _BY_PATTERN.search(question)
        if match is None:
            return None
        phrase = match.group(1)
        phrase = re.split(
            r"\b(?:in|for|with|where|from|during|using|over)\b", phrase
        )[0]
        tokens = set(
            token
            for token in phrase.split()
            if token not in _STOPWORDS and not token.isdigit()
        )
        if not tokens:
            return None

        best: tuple[int, str, str, str] | None = None
        for table in self._catalog.tables:
            for column in table.columns:
                column_tokens = set(
                    token
                    for token in _humanize(column.name).split()
                    if token not in _STOPWORDS
                )
                score = len(tokens & column_tokens)
                if score == 0:
                    continue
                candidate = (score, table.name, column.name, column.name)
                if best is None or (
                    -candidate[0],
                    candidate[1],
                    candidate[2],
                ) < (-best[0], best[1], best[2]):
                    best = candidate
        if best is None:
            return None
        _, table, column, output = best
        return _Dimension(
            table=table,
            column=column,
            output=output,
            role="dimension",
            kind="column",
        )

    def _measure(
        self, question: str, mentioned: set[str]
    ) -> _Measure | None:
        count = re.search(
            r"\b(how many|number of|count|counts|counted)\b", question
        )
        average = re.search(r"\b(average|avg|mean)\b", question)
        total = re.search(r"\b(total|sum|revenue|sales|gmv)\b", question)
        highest = re.search(r"\b(highest|maximum|max|largest|most)\b", question)
        lowest = re.search(r"\b(lowest|minimum|min|smallest|least)\b", question)

        if count is not None:
            return self._count_measure(question, mentioned)
        if average is not None:
            return self._average_measure(question, mentioned)
        if total is not None:
            return self._sum_measure(question, mentioned)
        if highest is not None:
            return self._numeric_measure(question, mentioned, "MAX", "max")
        if lowest is not None:
            return self._numeric_measure(question, mentioned, "MIN", "min")
        return None

    def _count_measure(
        self, question: str, mentioned: set[str]
    ) -> _Measure:
        table = self._count_table(question, mentioned)
        output = {
            "orders": "order_count",
            "customers": "customer_count",
            "order_items": "order_item_count",
            "order_payments": "payment_count",
            "order_reviews": "review_count",
            "products": "product_count",
            "sellers": "seller_count",
        }.get(table, "count")
        return _Measure(
            table=table,
            output=output,
            role="measure",
            template="COUNT(*)",
            columns=(),
        )

    def _count_table(self, question: str, mentioned: set[str]) -> str:
        for table, phrases in _COUNT_ALIASES:
            if self._catalog.get_table(table) is None:
                continue
            if any(_contains(question, phrase) for phrase in phrases):
                return table
        if mentioned:
            if "orders" in mentioned:
                return "orders"
            return sorted(mentioned)[0]
        if self._catalog.get_table("orders") is not None:
            return "orders"
        return self._catalog.tables[0].name

    def _average_measure(
        self, question: str, mentioned: set[str]
    ) -> _Measure | None:
        if _contains(question, "delivery time") or _contains(
            question, "delivery days"
        ) or _contains(question, "days to deliver"):
            if self._has_columns(
                "orders",
                "order_purchase_timestamp",
                "order_delivered_customer_date",
            ):
                return _Measure(
                    table="orders",
                    output="avg_delivery_days",
                    role="measure",
                    template=self._delivery_days_expression("{alias}"),
                    columns=(
                        ("orders", "order_purchase_timestamp"),
                        ("orders", "order_delivered_customer_date"),
                    ),
                )
        if _contains(question, "delivery delay") or _contains(
            question, "late delivery"
        ):
            if self._has_columns(
                "orders",
                "order_estimated_delivery_date",
                "order_delivered_customer_date",
            ):
                return _Measure(
                    table="orders",
                    output="avg_delivery_delay_days",
                    role="measure",
                    template=self._delivery_days_expression(
                        "{alias}", estimated=True
                    ),
                    columns=(
                        ("orders", "order_estimated_delivery_date"),
                        ("orders", "order_delivered_customer_date"),
                    ),
                )
        special = (
            (("review score", "rating", "ratings"), "order_reviews", "review_score", "avg_review_score"),
            (("shipping cost", "shipping", "freight"), "order_items", "freight_value", "avg_freight_value"),
            (("order value", "payment value", "payment"), "order_payments", "payment_value", "avg_payment_value"),
            (("price",), "order_items", "price", "avg_price"),
            (("weight",), "products", "product_weight_g", "avg_product_weight_g"),
            (("installments",), "order_payments", "payment_installments", "avg_payment_installments"),
        )
        for phrases, table, column, output in special:
            if any(_contains(question, phrase) for phrase in phrases):
                if self._has_columns(table, column):
                    return self._column_measure(table, column, "AVG", output)
        return self._numeric_measure(question, mentioned, "AVG", "avg")

    def _sum_measure(
        self, question: str, mentioned: set[str]
    ) -> _Measure | None:
        special = (
            (("revenue", "sales", "gmv", "payment value", "payment"), "order_payments", "payment_value", "total_payment_value"),
            (("freight", "shipping cost", "shipping"), "order_items", "freight_value", "total_freight_value"),
            (("price",), "order_items", "price", "total_price"),
            (("installments",), "order_payments", "payment_installments", "total_payment_installments"),
        )
        for phrases, table, column, output in special:
            if any(_contains(question, phrase) for phrase in phrases):
                if self._has_columns(table, column):
                    return self._column_measure(table, column, "SUM", output)
        return self._numeric_measure(question, mentioned, "SUM", "total")

    def _numeric_measure(
        self,
        question: str,
        mentioned: set[str],
        function: str,
        prefix: str,
    ) -> _Measure | None:
        tokens = set(
            token
            for token in question.split()
            if token not in _STOPWORDS and not token.isdigit()
        )
        best: tuple[int, str, str] | None = None
        for table in self._catalog.tables:
            for column in table.columns:
                if not self._is_numeric(column):
                    continue
                if column.name.lower() == "id" or column.name.lower().endswith("_id"):
                    continue
                column_tokens = set(_humanize(column.name).split())
                score = len(tokens & column_tokens)
                if table.name in mentioned:
                    score += 1
                if score == 0:
                    continue
                candidate = (score, table.name, column.name)
                if best is None or (
                    -candidate[0],
                    candidate[1],
                    candidate[2],
                ) < (-best[0], best[1], best[2]):
                    best = candidate
        if best is None:
            return None
        _, table, column = best
        return self._column_measure(
            table, column, function, f"{prefix}_{column}"
        )

    def _column_measure(
        self, table: str, column: str, function: str, output: str
    ) -> _Measure:
        return _Measure(
            table=table,
            output=output,
            role="measure",
            template=f"{function}({{alias}}.{column})",
            columns=((table, column),),
        )

    def _filters(
        self, question: str, linked: tuple[LinkedValue, ...]
    ) -> tuple[tuple[_Filter, ...], set[str]]:
        filters: list[_Filter] = []
        tables: set[str] = set()

        if self._has_columns("orders", "order_status"):
            for word, canonical in _STATUS_WORDS.items():
                if _contains(question, word):
                    filters.append(
                        _Filter(
                            table="orders",
                            column="order_status",
                            template=(
                                "{alias}.order_status = "
                                f"'{_escape_literal(canonical)}'"
                            ),
                        )
                    )
                    tables.add("orders")
                    break

        year_match = _YEAR_PATTERN.search(question)
        if year_match and self._has_columns(
            "orders", "order_purchase_timestamp"
        ):
            year = int(year_match.group(1))
            filters.append(
                _Filter(
                    table="orders",
                    column="order_purchase_timestamp",
                    template=(
                        "{alias}.order_purchase_timestamp >= "
                        f"'{year:04d}-01-01'"
                    ),
                )
            )
            filters.append(
                _Filter(
                    table="orders",
                    column="order_purchase_timestamp",
                    template=(
                        "{alias}.order_purchase_timestamp < "
                        f"'{year + 1:04d}-01-01'"
                    ),
                )
            )
            tables.add("orders")

        seen: set[tuple[str, str, str]] = set()
        for value in linked:
            if self._catalog.get_column(value.table, value.column) is None:
                continue
            key = (value.table, value.column, value.literal)
            if key in seen:
                continue
            seen.add(key)
            filters.append(
                _Filter(
                    table=value.table,
                    column=value.column,
                    template=(
                        f"{{alias}}.{value.column} = "
                        f"'{_escape_literal(value.literal)}'"
                    ),
                )
            )
            tables.add(value.table)

        deduped: dict[tuple[str, str, str], _Filter] = {}
        for item in filters:
            deduped.setdefault((item.table, item.column, item.template), item)
        unique_filters = list(deduped.values())
        unique_filters.sort(
            key=lambda item: (item.table, item.column, item.template)
        )
        return tuple(unique_filters), tables

    def _used_tables(self, base: str, required: set[str]) -> set[str]:
        used = {base}
        for target in sorted(required):
            if target == base:
                continue
            path = self._join_graph.find_path(base, target)
            if path is None:
                raise SQLGenerationError(
                    f"I understood the question as: {target}",
                    f"There is no approved join path between {base} and {target}.",
                )
            for edge in path:
                used.add(edge.left_table)
                used.add(edge.right_table)
        return used

    def _join_plan(
        self, base: str, used_tables: set[str]
    ) -> tuple[JoinEdge, ...] | None:
        if len(used_tables) == 1:
            return ()
        queue: deque[str] = deque([base])
        visited = {base}
        edges: list[JoinEdge] = []
        while queue:
            table = queue.popleft()
            for neighbor, edge in self._join_graph.neighbors(table):
                if neighbor in visited or neighbor not in {
                    item.lower() for item in used_tables
                }:
                    continue
                visited.add(neighbor)
                edges.append(edge)
                queue.append(neighbor)
        if len(visited) != len(used_tables):
            return None
        return tuple(edges)

    def _assign_aliases(self, tables: list[str]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        used: set[str] = set()
        for table in tables:
            base = _ALIAS_BASES.get(table, table[:1].lower() or "t")
            alias = base
            index = 2
            while alias in used:
                alias = f"{base}{index}"
                index += 1
            aliases[table] = alias
            used.add(alias)
        return aliases

    def _needed_columns(
        self,
        used_tables: set[str],
        selected: list[_Selected],
        filters: tuple[_Filter, ...],
        join_edges: tuple[JoinEdge, ...],
    ) -> dict[str, set[str]]:
        needed = {table: set() for table in used_tables}
        for item in selected:
            for table, column in item.columns:
                if table in needed:
                    needed[table].add(column)
        for item in filters:
            if item.table in needed:
                needed[item.table].add(item.column)
        for edge in join_edges:
            for left_column, right_column in edge.column_pairs:
                needed[edge.left_table].add(left_column)
                needed[edge.right_table].add(right_column)
        return needed

    def _allowlist(
        self, used_tables: set[str], needed: dict[str, set[str]]
    ) -> SchemaAllowlist:
        columns = tuple(
            AllowlistedColumn(table=table, column=column)
            for table in sorted(needed)
            for column in sorted(needed[table])
        )
        return SchemaAllowlist(
            tables=tuple(sorted(used_tables)),
            columns=columns,
        )

    def _render(
        self,
        *,
        base: str,
        ordered_tables: list[str],
        aliases: dict[str, str],
        join_edges: tuple[JoinEdge, ...],
        selected: list[_Selected],
        filters: tuple[_Filter, ...],
        dimension: _Dimension | None,
        measure: _Measure | None,
        needed: dict[str, set[str]],
        question: str,
    ) -> str:
        projection = ",\n       ".join(
            f"{item.template} AS {item.output}" for item in selected
        )

        if join_edges:
            ctes = []
            for table in ordered_tables:
                alias = aliases[table]
                columns = self._ordered_columns(table, needed[table])
                rendered_columns = ",\n               ".join(
                    f"{alias}.{column}" for column in columns
                )
                where = self._render_filters(table, filters, alias)
                ctes.append(
                    f"{alias} AS (\n"
                    f"    SELECT {rendered_columns}\n"
                    f"    FROM {table} AS {alias}{where}\n"
                    ")"
                )
            from_clause = f"FROM {aliases[base]}"
            joined = {base}
            for edge in join_edges:
                if edge.left_table in joined and edge.right_table not in joined:
                    left, right = edge.left_table, edge.right_table
                elif edge.right_table in joined and edge.left_table not in joined:
                    left, right = edge.right_table, edge.left_table
                else:
                    raise SQLGenerationError(
                        "I understood the requested tables.",
                        "The join plan is ambiguous; please clarify the grain.",
                    )
                left_alias = aliases[left]
                right_alias = aliases[right]
                predicates = []
                for left_column, right_column in edge.column_pairs:
                    if edge.left_table != left:
                        left_column, right_column = right_column, left_column
                    predicates.append(
                        f"{left_alias}.{left_column} = "
                        f"{right_alias}.{right_column}"
                    )
                from_clause += (
                    f"\nJOIN {right_alias} ON "
                    + " AND ".join(predicates)
                )
                joined.add(right)
            prefix = "WITH " + ",\n".join(ctes) + "\n"
            where = ""
        else:
            prefix = ""
            from_clause = f"FROM {base} AS {aliases[base]}"
            where = self._render_filters(base, filters, aliases[base])

        group_by = ""
        if measure is not None and dimension is not None:
            group_by = (
                "\nGROUP BY "
                + self._dimension_expression(dimension, aliases[dimension.table])
            )

        order_by = self._render_order_by(
            question=question,
            dimension=dimension,
            measure=measure,
        )
        limit = self._render_limit(
            question=question, measure=measure, dimension=dimension
        )

        return (
            f"{prefix}SELECT {projection}\n"
            f"{from_clause}"
            f"{where}"
            f"{group_by}"
            f"{order_by}"
            f"\nLIMIT {limit}"
        )

    def _render_filters(
        self, table: str, filters: tuple[_Filter, ...], alias: str
    ) -> str:
        clauses = [
            item.template.format(alias=alias)
            for item in filters
            if item.table == table
        ]
        if not clauses:
            return ""
        return "\n    WHERE " + "\n      AND ".join(clauses)

    def _render_order_by(
        self,
        *,
        question: str,
        dimension: _Dimension | None,
        measure: _Measure | None,
    ) -> str:
        top_match = _TOP_PATTERN.search(question)
        if top_match and measure is not None:
            return f"\nORDER BY {measure.output} DESC"
        if dimension is not None:
            return f"\nORDER BY {dimension.output} ASC"
        return ""

    def _render_limit(
        self,
        *,
        question: str,
        measure: _Measure | None,
        dimension: _Dimension | None,
    ) -> int:
        top_match = _TOP_PATTERN.search(question)
        if top_match:
            return min(max(1, int(top_match.group(1))), self._limit)
        if measure is not None and dimension is None:
            return 1
        return self._limit

    def _ordered_columns(
        self, table: str, columns: set[str]
    ) -> tuple[str, ...]:
        entry = self._catalog.get_table(table)
        if entry is None:
            raise SQLGenerationError(
                "I understood the requested table.",
                f"The table {table} is not in the catalog.",
            )
        ordered = tuple(
            column.name for column in entry.columns if column.name in columns
        )
        unknown = columns - set(ordered)
        if unknown:
            raise SQLGenerationError(
                "I understood the requested columns.",
                f"Unknown columns for {table}: {', '.join(sorted(unknown))}.",
            )
        return ordered

    def _list_columns(
        self,
        base: str,
        dimension: _Dimension | None,
        aliases: dict[str, str],
    ) -> list[_Selected]:
        table = self._catalog.get_table(base)
        if table is None:
            return []
        alias = aliases[base]
        selected: list[_Selected] = []
        key = next(
            (
                column
                for column in table.columns
                if column.name.lower() == "id"
                or column.name.lower().endswith(_KEY_SUFFIXES)
            ),
            None,
        )
        if key is not None:
            selected.append(
                _Selected(
                    table=base,
                    output=key.name,
                    role="key",
                    template=f"{alias}.{key.name}",
                    columns=((base, key.name),),
                )
            )
        if dimension is not None and (
            key is None or dimension.column != key.name
        ):
            selected.append(
                _Selected(
                    table=dimension.table,
                    output=dimension.output,
                    role=dimension.role,
                    template=self._dimension_expression(
                        dimension, aliases[dimension.table]
                    ),
                    columns=((dimension.table, dimension.column),),
                )
            )
        if selected:
            return selected
        return [
            _Selected(
                table=base,
                output=column.name,
                role="dimension",
                template=f"{alias}.{column.name}",
                columns=((base, column.name),),
            )
            for column in table.columns[:4]
        ]

    def _dimension_expression(self, dimension: _Dimension, alias: str) -> str:
        column = f"{alias}.{dimension.column}"
        if dimension.kind == "month":
            if self._dialect == "sqlite":
                return f"strftime('%Y-%m', {column})"
            if self._dialect == "mysql":
                return f"DATE_FORMAT({column}, '%Y-%m')"
            if self._dialect in ("postgres", "postgresql"):
                return f"to_char({column}, 'YYYY-MM')"
            return f"strftime({column}, '%Y-%m')"
        if dimension.kind == "year":
            if self._dialect == "sqlite":
                return f"strftime('%Y', {column})"
            if self._dialect == "mysql":
                return f"DATE_FORMAT({column}, '%Y')"
            if self._dialect in ("postgres", "postgresql"):
                return f"to_char({column}, 'YYYY')"
            return f"strftime({column}, '%Y')"
        return column

    def _delivery_days_expression(self, alias: str, *, estimated: bool = False) -> str:
        end_column = "order_estimated_delivery_date" if estimated else "order_delivered_customer_date"
        start_column = "order_delivered_customer_date" if estimated else "order_purchase_timestamp"
        start = f"{alias}.{start_column}"
        end = f"{alias}.{end_column}"
        if self._dialect == "sqlite":
            return f"AVG(julianday({end}) - julianday({start}))"
        if self._dialect == "mysql":
            return f"AVG(TIMESTAMPDIFF(DAY, {start}, {end}))"
        return f"AVG(date_diff('day', {start}, {end}))"

    def _has_columns(self, table: str, *columns: str) -> bool:
        return all(
            self._catalog.get_column(table, column) is not None
            for column in columns
        )

    @staticmethod
    def _is_numeric(column: CatalogColumn) -> bool:
        upper = column.data_type.upper()
        return any(part in upper for part in _NUMERIC_TYPES)


__all__ = ["GenerationResult", "SQLGenerationError", "SQLGenerator"]
