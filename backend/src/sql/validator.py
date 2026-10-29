"""SQLGlot AST validator (SAFE-1, SAFE-2, SQL-2 to SQL-7, SQL-17).

Core gates are always active: one read-only statement, no DML/DDL/file access
or system catalogs, and every physical table must be in the retrieved allowlist.
Enterprise mode additionally requires explicit projections and a bounded result;
benchmark mode relaxes only those two rules so BIRD gold result sets survive.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from contracts.models import ValidationCheck, ValidationMode, ValidationResult

_READ_ONLY_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)

_FORBIDDEN_NODE_NAMES = frozenset(
    {
        "Insert",
        "Update",
        "Delete",
        "Create",
        "Drop",
        "Alter",
        "Truncate",
        "TruncateTable",
        "Merge",
        "Grant",
        "Revoke",
        "Command",
        "Transaction",
        "Commit",
        "Rollback",
        "Attach",
        "Detach",
        "Pragma",
        "Copy",
        "LoadData",
        "Export",
        "Use",
        "Set",
    }
)

_BANNED_FUNCTIONS = frozenset(
    {
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "read_json",
        "read_json_auto",
        "read_text",
        "read_blob",
        "read_xlsx",
        "load_file",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "xp_cmdshell",
        "lo_import",
        "lo_export",
        "openrowset",
        "opendatasource",
        "duckdb_tables",
        "duckdb_columns",
        "duckdb_views",
        "duckdb_indexes",
        "duckdb_settings",
    }
)

_SYSTEM_SCHEMAS = frozenset(
    {"information_schema", "pg_catalog", "performance_schema", "mysql", "sys"}
)

_SYSTEM_TABLES = frozenset(
    {
        "sqlite_master",
        "sqlite_schema",
        "sqlite_temp_master",
        "duckdb_tables",
        "duckdb_columns",
        "duckdb_views",
        "duckdb_indexes",
        "duckdb_settings",
    }
)

_COMMON_SCHEMAS = frozenset({"main", "public", "dbo"})

_COMMENT_PATTERN = re.compile(r"--|/\*|\*/")


def _normalize_identifier(name: str) -> str:
    return name.strip().strip('`"[]').lower()


def _unwrap_root(expression: exp.Expression) -> exp.Expression:
    while isinstance(expression, exp.Subquery) and expression.this is not None:
        expression = expression.this
    return expression


def _function_name(node: exp.Expression) -> str | None:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    if isinstance(node, exp.Func):
        return node.sql_name().lower()
    return None


def _physical_tables(ast: exp.Expression) -> Iterator[exp.Table]:
    cte_names = {cte.alias_or_name.lower() for cte in ast.find_all(exp.CTE)}

    for table in ast.find_all(exp.Table):
        name = table.name
        if not name:
            continue
        if not table.db and name.lower() in cte_names:
            continue
        yield table


def _table_label(table: exp.Table) -> str:
    return ".".join(part for part in (table.catalog, table.db, table.name) if part)


def _star_projections(ast: exp.Expression) -> tuple[str, ...]:
    stars: list[str] = []
    for select in ast.find_all(exp.Select):
        for projection in select.expressions:
            if isinstance(projection, exp.Star):
                stars.append(projection.sql())
            elif isinstance(projection, exp.Column) and isinstance(
                projection.this, exp.Star
            ):
                stars.append(projection.sql())
    return tuple(stars)


def _has_row_bound(ast: exp.Expression) -> bool:
    root = _unwrap_root(ast)
    return any(
        root.args.get(key) is not None for key in ("limit", "fetch", "top")
    )


class SQLValidator:
    """Deterministic validator built on the SQLGlot AST."""

    def __init__(
        self,
        allowlist: Iterable[str] | str,
        *,
        dialect: str = "duckdb",
        mode: ValidationMode = "enterprise",
        columns: Iterable[str] | str | None = None,
    ) -> None:
        if isinstance(allowlist, str):
            allowlist = (allowlist,)
        if mode not in ("enterprise", "benchmark"):
            raise ValueError("mode must be 'enterprise' or 'benchmark'")

        sqlglot.Dialect.get_or_raise(dialect)

        self._allowlist = frozenset(
            _normalize_identifier(name) for name in allowlist
        )
        self._columns = self._parse_columns(columns)
        self.dialect = dialect
        self.mode = mode

    @property
    def allowlist(self) -> frozenset[str]:
        return self._allowlist

    @property
    def columns(self) -> frozenset[tuple[str, str]] | None:
        return self._columns

    @staticmethod
    def _parse_columns(
        columns: Iterable[str] | str | None,
    ) -> frozenset[tuple[str, str]] | None:
        if columns is None:
            return None
        if isinstance(columns, str):
            columns = (columns,)
        parsed: set[tuple[str, str]] = set()
        for entry in columns:
            parts = entry.split(".")
            if len(parts) != 2 or not all(part.strip() for part in parts):
                raise ValueError(
                    "column allowlist entries must be 'table.column'"
                )
            parsed.add(
                (
                    _normalize_identifier(parts[0]),
                    _normalize_identifier(parts[1]),
                )
            )
        return frozenset(parsed)

    def validate(self, sql: str) -> ValidationResult:
        checks: list[ValidationCheck] = []

        if not sql.strip():
            checks.append(
                ValidationCheck(
                    id=1, name="parse", status="fail", reason="SQL is empty"
                )
            )
            return self._result(checks)

        try:
            statements = [
                statement
                for statement in sqlglot.parse(sql, read=self.dialect)
                if statement is not None
            ]
        except ParseError as exc:
            reason = str(exc).splitlines()[0][:300]
            checks.append(
                ValidationCheck(
                    id=1, name="parse", status="fail", reason=reason
                )
            )
            return self._result(checks)

        checks.append(ValidationCheck(id=1, name="parse", status="pass"))

        if len(statements) != 1:
            checks.append(
                ValidationCheck(
                    id=2,
                    name="single_select",
                    status="fail",
                    reason=f"expected exactly one statement, found {len(statements)}",
                )
            )
            return self._result(checks)

        checks.append(ValidationCheck(id=2, name="single_select", status="pass"))

        ast = statements[0]
        root = _unwrap_root(ast)
        forbidden_nodes = sorted(
            {
                type(node).__name__
                for node in ast.walk()
                if type(node).__name__ in _FORBIDDEN_NODE_NAMES
            }
        )
        banned_functions = sorted(
            {
                name
                for node in ast.walk()
                if (name := _function_name(node)) in _BANNED_FUNCTIONS
            }
        )
        system_tables = sorted(
            {
                _table_label(table)
                for table in ast.find_all(exp.Table)
                if (table.db or "").lower() in _SYSTEM_SCHEMAS
                or table.name.lower() in _SYSTEM_TABLES
            }
        )

        core_problems: list[str] = []
        if not isinstance(root, _READ_ONLY_ROOTS):
            core_problems.append(
                f"root must be a read-only SELECT, got {type(root).__name__}"
            )
        if forbidden_nodes:
            core_problems.append(
                "write or administrative statements are forbidden "
                f"({', '.join(forbidden_nodes)})"
            )
        if banned_functions:
            core_problems.append(
                "file-reading or system functions are forbidden "
                f"({', '.join(banned_functions)})"
            )
        if system_tables:
            core_problems.append(
                "system catalogs are forbidden "
                f"({', '.join(system_tables)})"
            )
        if _COMMENT_PATTERN.search(sql):
            core_problems.append("SQL comments are not allowed")

        core_ok = not core_problems
        if core_ok:
            checks.append(ValidationCheck(id=3, name="no_dml_ddl", status="pass"))
        else:
            offending = tuple(
                sorted(set(forbidden_nodes) | set(banned_functions) | set(system_tables))
            )
            checks.append(
                ValidationCheck(
                    id=3,
                    name="no_dml_ddl",
                    status="fail",
                    reason="; ".join(core_problems),
                    offending=offending or None,
                )
            )

        unknown_tables = sorted(
            {
                _table_label(table)
                for table in _physical_tables(ast)
                if not self._table_is_allowed(table)
            }
        )
        unknown_columns = self._unknown_columns(ast)
        if unknown_tables or unknown_columns:
            if unknown_tables and unknown_columns:
                reason = "table and column are outside the retrieved allowlist"
            elif unknown_tables:
                reason = "table is outside the retrieved allowlist"
            else:
                reason = "column is outside the retrieved allowlist"
            checks.append(
                ValidationCheck(
                    id=4,
                    name="allowlist",
                    status="fail",
                    reason=reason,
                    offending=tuple(unknown_tables) + unknown_columns,
                )
            )
        else:
            checks.append(ValidationCheck(id=4, name="allowlist", status="pass"))

        checks.append(
            ValidationCheck(
                id=5,
                name="approved_joins_fanout",
                status="skipped",
                reason="no join graph supplied to this validator",
            )
        )

        checks.append(self._limits_check(ast, root, core_ok))

        return self._result(checks)

    def _unknown_columns(self, ast: exp.Expression) -> tuple[str, ...]:
        if self._columns is None:
            return ()

        allowed_by_table: dict[str, set[str]] = {}
        for table, column in self._columns:
            allowed_by_table.setdefault(table, set()).add(column)
        all_columns = {column for _, column in self._columns}

        cte_names = {cte.alias_or_name.lower() for cte in ast.find_all(exp.CTE)}
        alias_to_table: dict[str, str] = {}
        for table in ast.find_all(exp.Table):
            name = table.name
            if not name:
                continue
            if not table.db and name.lower() in cte_names:
                continue
            physical = name.lower()
            alias_to_table[physical] = physical
            alias_to_table[table.alias_or_name.lower()] = physical

        cte_outputs = {
            cte.alias_or_name.lower(): self._cte_output_names(
                cte, allowed_by_table, all_columns
            )
            for cte in ast.find_all(exp.CTE)
        }
        select_aliases = {
            alias.alias.lower()
            for alias in ast.find_all(exp.Alias)
            if alias.alias
        }
        physical_tables = sorted(set(alias_to_table.values()))

        unknown: set[str] = set()
        for column in ast.find_all(exp.Column):
            if isinstance(column.this, exp.Star):
                continue
            name = column.name.lower()
            if not name:
                continue
            qualifier = column.table.lower()

            if qualifier:
                if qualifier in cte_outputs:
                    outputs = cte_outputs[qualifier]
                    if outputs:
                        if name not in outputs:
                            unknown.add(f"{qualifier}.{name}")
                        continue
                    table = alias_to_table.get(qualifier)
                    if table is None or (table, name) not in self._columns:
                        unknown.add(f"{qualifier}.{name}")
                    continue

                table = alias_to_table.get(qualifier)
                if table is None:
                    table = qualifier if qualifier in allowed_by_table else None
                if table is None or (table, name) not in self._columns:
                    unknown.add(
                        f"{table}.{name}" if table is not None else f"{qualifier}.{name}"
                    )
                continue

            if name in select_aliases:
                continue

            select = column.find_ancestor(exp.Select)
            sources = self._select_sources(select) if select is not None else ()
            cte_sources = [
                source for source in sources if source in cte_outputs
            ]
            physical_sources = [
                source
                for source in sources
                if source not in cte_outputs and source in allowed_by_table
            ]
            if cte_sources:
                outputs = set().union(
                    *(cte_outputs[source] for source in cte_sources)
                )
                if name in outputs:
                    continue
                if any(
                    (source, name) in self._columns
                    for source in physical_sources
                ):
                    continue
                unknown.add(f"{cte_sources[0]}.{name}")
                continue

            if physical_sources:
                if any(
                    (source, name) in self._columns
                    for source in physical_sources
                ):
                    continue
                unknown.add(f"{physical_sources[0]}.{name}")
                continue

            if name in all_columns:
                continue
            if len(physical_tables) == 1:
                unknown.add(f"{physical_tables[0]}.{name}")
            else:
                unknown.add(name)

        return tuple(sorted(unknown))

    @staticmethod
    def _select_sources(select: exp.Select) -> tuple[str, ...]:
        tables: list[str] = []
        from_clause = select.args.get("from_") or select.args.get("from")
        if from_clause is not None and isinstance(from_clause.this, exp.Table):
            tables.append(from_clause.this.name.lower())
        for join in select.args.get("joins") or ():
            if isinstance(join.this, exp.Table):
                tables.append(join.this.name.lower())
        return tuple(tables)

    def _cte_output_names(
        self,
        cte: exp.CTE,
        allowed_by_table: dict[str, set[str]],
        all_columns: set[str],
    ) -> set[str]:
        outputs: set[str] = set()
        source = self._cte_source_table(cte)
        for projection in cte.this.expressions if isinstance(cte.this, exp.Select) else ():
            if isinstance(projection, exp.Alias):
                outputs.add(projection.alias.lower())
            elif isinstance(projection, exp.Star):
                outputs.update(
                    allowed_by_table.get(source, all_columns)
                    if source is not None
                    else all_columns
                )
            elif isinstance(projection, exp.Column) and isinstance(
                projection.this, exp.Star
            ):
                outputs.update(
                    allowed_by_table.get(source, all_columns)
                    if source is not None
                    else all_columns
                )
            elif isinstance(projection, exp.Column) and projection.name:
                outputs.add(projection.name.lower())
        return outputs

    def _cte_source_table(self, cte: exp.CTE) -> str | None:
        cte_names = {item.alias_or_name.lower() for item in cte.find_all(exp.CTE)}
        for table in cte.this.find_all(exp.Table):
            if not table.db and table.name.lower() in cte_names:
                continue
            return table.name.lower()
        return None

    def _table_is_allowed(self, table: exp.Table) -> bool:
        bare = table.name.lower()
        schema = (table.db or "").lower()
        full = ".".join(
            part for part in (table.catalog, table.db, table.name) if part
        ).lower()

        if full in self._allowlist:
            return True
        if not table.catalog and not schema and any(
            entry.endswith(f".{bare}") for entry in self._allowlist
        ):
            return True
        return bare in self._allowlist and (
            not table.catalog and (not schema or schema in _COMMON_SCHEMAS)
        )

    def _limits_check(
        self,
        ast: exp.Expression,
        root: exp.Expression,
        core_ok: bool,
    ) -> ValidationCheck:
        if not core_ok:
            return ValidationCheck(
                id=6,
                name="limits_bounds",
                status="skipped",
                reason="not evaluated because the statement is not a read-only SELECT",
            )

        if self.mode == "benchmark":
            return ValidationCheck(
                id=6,
                name="limits_bounds",
                status="skipped",
                reason="benchmark mode relaxes row limits and SELECT * restrictions",
            )

        problems: list[str] = []
        offending: list[str] = []

        stars = _star_projections(ast)
        if stars:
            problems.append("SELECT * is not allowed in enterprise mode")
            offending.extend(stars)
        if not _has_row_bound(root):
            problems.append("enterprise queries require an explicit LIMIT")

        if problems:
            return ValidationCheck(
                id=6,
                name="limits_bounds",
                status="fail",
                reason="; ".join(problems),
                offending=tuple(offending) or None,
            )

        return ValidationCheck(id=6, name="limits_bounds", status="pass")

    def _result(self, checks: list[ValidationCheck]) -> ValidationResult:
        return ValidationResult(
            approved=all(check.status != "fail" for check in checks),
            validation_mode=self.mode,
            checks=tuple(checks),
        )


def validate_sql(
    sql: str,
    allowlist: Iterable[str] | str,
    *,
    dialect: str = "duckdb",
    mode: ValidationMode = "enterprise",
) -> ValidationResult:
    """Convenience wrapper around :class:`SQLValidator`."""

    return SQLValidator(allowlist, dialect=dialect, mode=mode).validate(sql)


__all__ = ["SQLValidator", "validate_sql"]
