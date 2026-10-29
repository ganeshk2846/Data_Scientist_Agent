"""Tests for the local schema catalog used by perception and answerability."""

import sqlite3

from answerability import AnswerabilityChecker
from contracts.models import GatewayConfig
from gateway.connection import ConnectionManager
from schema_retriever.catalog import SchemaCatalog
from schema_retriever.perceptor import SchemaPerceptor


def _make_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE customers (
            customer_id TEXT,
            customer_state TEXT,
            customer_city TEXT,
            email TEXT,
            signup_date TEXT
        );
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            order_status TEXT,
            payment_value REAL
        );
        CREATE TABLE order_payments (
            order_id TEXT REFERENCES orders(order_id),
            payment_sequential INTEGER,
            payment_type TEXT,
            payment_value REAL
        );
        INSERT INTO customers VALUES
            ('c1', 'SP', 'sao paulo', 'one@example.com', '2017-01-01'),
            ('c2', 'RJ', 'rio de janeiro', 'two@example.com', '2017-01-02'),
            ('c3', 'SP', 'campinas', 'three@example.com', '2017-01-03');
        INSERT INTO orders VALUES
            ('o1', 'delivered', 120.5),
            ('o2', 'shipped', 80.0);
        INSERT INTO order_payments VALUES
            ('o1', 1, 'credit_card', 120.5),
            ('o2', 1, 'boleto', 80.0);
        """
    )
    connection.commit()
    connection.close()


def _manager(path):
    return ConnectionManager(
        GatewayConfig(
            datasource_id="catalog-test",
            dialect="sqlite",
            connection_url=str(path),
            timeout_ms=5_000,
        )
    )


def test_catalog_profiles_categorical_values_and_skips_private_columns(tmp_path):
    path = tmp_path / "shop.sqlite"
    _make_database(path)
    manager = _manager(path)

    try:
        catalog = SchemaCatalog.from_manager(manager)
    finally:
        manager.dispose()

    customers = catalog.get_table("customers")
    assert customers is not None
    columns = {column.name: column for column in customers.columns}

    assert columns["customer_state"].values == ("RJ", "SP")
    assert columns["customer_city"].values == (
        "campinas",
        "rio de janeiro",
        "sao paulo",
    )
    assert columns["customer_id"].values == ()
    assert columns["email"].values == ()
    assert columns["signup_date"].values == ()
    assert catalog.get_column("orders", "payment_value").values == ()
    assert (
        catalog.get_column("order_payments", "payment_sequential").values
        == ()
    )
    assert catalog.get_table("order_payments") is not None
    assert catalog.version


def test_catalog_records_declared_foreign_keys_and_unique_keys(tmp_path):
    path = tmp_path / "shop.sqlite"
    _make_database(path)
    manager = _manager(path)

    try:
        catalog = SchemaCatalog.from_manager(manager)
    finally:
        manager.dispose()

    orders = catalog.get_table("orders")
    payments = catalog.get_table("order_payments")
    assert orders is not None and orders.unique_keys == (("order_id",),)
    assert payments is not None
    assert payments.foreign_keys[0].columns == ("order_id",)
    assert payments.foreign_keys[0].referred_table == "orders"
    assert payments.foreign_keys[0].referred_columns == ("order_id",)


def test_catalog_keeps_columns_but_drops_values_above_cardinality_limit(tmp_path):
    path = tmp_path / "shop.sqlite"
    _make_database(path)
    manager = _manager(path)

    try:
        catalog = SchemaCatalog.from_manager(manager, max_cardinality=1)
    finally:
        manager.dispose()

    column = catalog.get_column("customers", "customer_state")
    assert column is not None
    assert column.values == ()


def test_catalog_version_is_stable_and_changes_when_values_change(tmp_path):
    path = tmp_path / "shop.sqlite"
    _make_database(path)

    manager = _manager(path)
    try:
        first = SchemaCatalog.from_manager(manager)
    finally:
        manager.dispose()

    manager = _manager(path)
    try:
        second = SchemaCatalog.from_manager(manager)
    finally:
        manager.dispose()

    assert first.version == second.version

    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO customers VALUES "
        "('c4', 'MG', 'belo horizonte', 'four@example.com', '2017-01-04')"
    )
    connection.commit()
    connection.close()

    manager = _manager(path)
    try:
        third = SchemaCatalog.from_manager(manager)
    finally:
        manager.dispose()

    assert third.version != first.version
    assert "MG" in third.get_column("customers", "customer_state").values


def test_catalog_exposes_human_readable_domains(tmp_path):
    path = tmp_path / "shop.sqlite"
    _make_database(path)
    manager = _manager(path)

    try:
        catalog = SchemaCatalog.from_manager(manager)
    finally:
        manager.dispose()

    assert catalog.domains == tuple(sorted(catalog.domains))
    assert "order payments" in catalog.domains
    assert "customers" in catalog.domains


def test_catalog_lookups_are_read_only_views(tmp_path):
    path = tmp_path / "shop.sqlite"
    _make_database(path)
    manager = _manager(path)

    try:
        catalog = SchemaCatalog.from_manager(manager)
    finally:
        manager.dispose()

    tables = catalog.get_tables(("orders", "missing"))
    assert tuple(table.name for table in tables) == ("orders",)
    assert catalog.get_table("missing") is None
    assert catalog.get_column("missing", "anything") is None


def test_catalog_grounds_answerability_and_value_linking(tmp_path):
    path = tmp_path / "shop.sqlite"
    _make_database(path)
    manager = _manager(path)

    try:
        catalog = SchemaCatalog.from_manager(manager)
    finally:
        manager.dispose()

    checker = AnswerabilityChecker(catalog)
    perceptor = SchemaPerceptor(catalog)

    supported = checker.check("How many customers from SP?")
    perception = perceptor.perceive(
        "How many customers from SP?", tables={"customers"}
    )
    refused = checker.check("What is the profit margin by state?")

    assert supported.answerable is True
    assert any(
        value.table == "customers"
        and value.column == "customer_state"
        and value.literal == "SP"
        for value in perception.linked_values
    )
    assert refused.answerable is False
    assert "profit" in refused.missing
    assert refused.closest_answerable is not None
