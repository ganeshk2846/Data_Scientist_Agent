"""Tests for the SQLGlot AST validator (SAFE-1, SAFE-2, SQL-2 to SQL-7, SQL-17).

Core safety gates are always on: one read-only statement, no DML/DDL/file or
system-catalog access, and every physical table inside the retrieved allowlist.
Enterprise mode adds explicit projections and a bounded result; benchmark mode
relaxes those two enterprise-only rules to preserve BIRD result sets.
"""

import pytest

from contracts.models import ValidationResult
from sql.validator import SQLValidator, validate_sql

ALLOWLIST = ("customers", "orders", "order_items", "products")
DIALECT = "duckdb"


def enterprise() -> SQLValidator:
    return SQLValidator(ALLOWLIST, dialect=DIALECT, mode="enterprise")


def benchmark() -> SQLValidator:
    return SQLValidator(ALLOWLIST, dialect=DIALECT, mode="benchmark")


def check(result: ValidationResult, name: str):
    return next(item for item in result.checks if item.name == name)


def test_accepts_a_bounded_explicit_select():
    result = enterprise().validate(
        "SELECT region, SUM(revenue) AS revenue "
        "FROM orders GROUP BY region LIMIT 100"
    )

    assert result.approved is True
    assert result.validation_mode == "enterprise"
    assert check(result, "parse").status == "pass"
    assert check(result, "single_select").status == "pass"
    assert check(result, "no_dml_ddl").status == "pass"
    assert check(result, "allowlist").status == "pass"
    assert check(result, "limits_bounds").status == "pass"


def test_accepts_read_only_ctes():
    result = enterprise().validate(
        "WITH recent AS ("
        "  SELECT customer_id, amount FROM orders WHERE status = 'paid'"
        ") "
        "SELECT customer_id, SUM(amount) AS total "
        "FROM recent GROUP BY customer_id LIMIT 50"
    )

    assert result.approved is True
    assert check(result, "allowlist").status == "pass"


def test_allows_qualified_tables_and_set_operations():
    result = enterprise().validate(
        "SELECT o.customer_id FROM main.orders AS o "
        "UNION "
        "SELECT c.id FROM customers AS c "
        "LIMIT 25"
    )

    assert result.approved is True


def test_rejects_parse_errors():
    result = enterprise().validate("SELECT * FROM orders WHERE (")

    assert result.approved is False
    assert check(result, "parse").status == "fail"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT id FROM orders; DROP TABLE orders",
        "SELECT id FROM orders; INSERT INTO orders VALUES (1)",
    ],
)
def test_rejects_stacked_statements(sql):
    result = enterprise().validate(sql)

    assert result.approved is False
    assert check(result, "single_select").status == "fail"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders (id) VALUES (1)",
        "UPDATE orders SET id = 1",
        "DELETE FROM orders",
        "DROP TABLE orders",
        "CREATE TABLE copied AS SELECT id FROM orders",
        "EXPLAIN SELECT id FROM orders",
    ],
)
def test_rejects_non_select_roots(sql):
    result = enterprise().validate(sql)

    assert result.approved is False
    assert check(result, "no_dml_ddl").status == "fail"


def test_rejects_an_unknown_table():
    result = enterprise().validate("SELECT id FROM hidden_orders LIMIT 10")

    assert result.approved is False
    allowlist_check = check(result, "allowlist")
    assert allowlist_check.status == "fail"
    assert allowlist_check.offending == ("hidden_orders",)


def test_rejects_an_unknown_table_inside_a_cte():
    result = enterprise().validate(
        "WITH x AS (SELECT id FROM hidden_orders) SELECT id FROM x LIMIT 10"
    )

    assert result.approved is False
    assert check(result, "allowlist").offending == ("hidden_orders",)


def test_allowlist_is_case_insensitive():
    result = enterprise().validate("SELECT id FROM ORDERS LIMIT 10")

    assert result.approved is True


def test_rejects_a_table_outside_the_approved_schema():
    result = enterprise().validate("SELECT id FROM evil.orders LIMIT 10")

    assert result.approved is False
    assert check(result, "allowlist").status == "fail"


@pytest.mark.parametrize(
    ("allowlist", "sql"),
    [
        (("orders",), "SELECT id FROM foreign_catalog.main.orders LIMIT 10"),
        (("main.orders",), "SELECT id FROM foreign_catalog.orders LIMIT 10"),
    ],
)
def test_rejects_unapproved_catalog_qualifiers(allowlist, sql):
    result = SQLValidator(
        allowlist, dialect=DIALECT, mode="benchmark"
    ).validate(sql)

    assert result.approved is False
    assert check(result, "allowlist").status == "fail"


def test_accepts_an_exact_catalog_qualified_allowlist_entry():
    result = SQLValidator(
        ("foreign_catalog.main.orders",),
        dialect=DIALECT,
        mode="benchmark",
    ).validate("SELECT id FROM foreign_catalog.main.orders LIMIT 10")

    assert result.approved is True


def test_rejects_system_catalog_access():
    result = enterprise().validate(
        "SELECT table_name FROM information_schema.tables LIMIT 10"
    )

    assert result.approved is False
    assert check(result, "no_dml_ddl").status == "fail"


def test_rejects_file_reading_functions():
    result = enterprise().validate(
        "SELECT read_csv('/etc/passwd') AS leaked LIMIT 1"
    )

    assert result.approved is False
    assert check(result, "no_dml_ddl").status == "fail"


def test_rejects_sql_comments():
    result = enterprise().validate(
        "SELECT id FROM orders -- bypass the filter\nLIMIT 10"
    )

    assert result.approved is False
    assert check(result, "no_dml_ddl").status == "fail"


def test_enterprise_rejects_select_star():
    result = enterprise().validate("SELECT * FROM orders LIMIT 10")

    assert result.approved is False
    limits = check(result, "limits_bounds")
    assert limits.status == "fail"
    assert "SELECT *" in limits.reason


def test_enterprise_rejects_qualified_star():
    result = enterprise().validate("SELECT o.* FROM orders AS o LIMIT 10")

    assert result.approved is False
    assert check(result, "limits_bounds").status == "fail"


def test_enterprise_requires_a_limit():
    result = enterprise().validate("SELECT id FROM orders")

    assert result.approved is False
    limits = check(result, "limits_bounds")
    assert limits.status == "fail"
    assert "LIMIT" in limits.reason


def test_enterprise_allows_count_star():
    result = enterprise().validate("SELECT COUNT(*) AS n FROM orders LIMIT 1")

    assert result.approved is True


def test_benchmark_relaxes_star_and_limit_rules():
    result = benchmark().validate("SELECT * FROM orders")

    assert result.approved is True
    assert result.validation_mode == "benchmark"
    assert check(result, "limits_bounds").status == "skipped"


def test_benchmark_still_enforces_the_core_gates():
    unknown = benchmark().validate("SELECT * FROM hidden_orders")
    write = benchmark().validate("DROP TABLE orders")
    stacked = benchmark().validate("SELECT 1; SELECT 2")

    assert unknown.approved is False
    assert check(unknown, "allowlist").status == "fail"
    assert write.approved is False
    assert check(write, "no_dml_ddl").status == "fail"
    assert stacked.approved is False
    assert check(stacked, "single_select").status == "fail"


def test_convenience_function_matches_the_class():
    sql = "SELECT id FROM orders LIMIT 10"

    assert validate_sql(sql, ALLOWLIST, dialect=DIALECT) == enterprise().validate(sql)


def column_validator() -> SQLValidator:
    return SQLValidator(
        ("orders", "customers"),
        dialect=DIALECT,
        mode="enterprise",
        columns=(
            "orders.id",
            "orders.customer_id",
            "orders.amount",
            "customers.id",
            "customers.customer_state",
        ),
    )


def test_rejects_a_column_outside_the_retrieved_allowlist():
    result = column_validator().validate(
        "SELECT id, secret FROM orders LIMIT 10"
    )

    assert result.approved is False
    allowlist = check(result, "allowlist")
    assert allowlist.status == "fail"
    assert allowlist.offending == ("orders.secret",)


def test_checks_qualified_columns_against_their_table():
    valid = column_validator().validate(
        "SELECT c.customer_state FROM orders AS o "
        "JOIN customers AS c ON o.customer_id = c.id LIMIT 10"
    )
    invalid = column_validator().validate(
        "SELECT o.customer_state FROM orders AS o LIMIT 10"
    )

    assert valid.approved is True
    assert invalid.approved is False
    assert check(invalid, "allowlist").offending == (
        "orders.customer_state",
    )


def test_accepts_columns_produced_by_a_cte():
    result = column_validator().validate(
        "WITH recent AS ("
        "  SELECT id, amount FROM orders"
        ") "
        "SELECT id, amount FROM recent LIMIT 10"
    )

    assert result.approved is True


def test_rejects_a_cte_column_not_present_in_the_cte_projection():
    result = column_validator().validate(
        "WITH recent AS (SELECT id FROM orders) "
        "SELECT id, amount FROM recent LIMIT 10"
    )

    assert result.approved is False
    assert check(result, "allowlist").offending == ("recent.amount",)
