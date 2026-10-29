"""Integration checks for catalog-grounded SQL generation (GRD-5/6/7/8/9, SAFE-1/5)."""
import json
import itertools
import sqlite3
from types import SimpleNamespace

import pytest

from src import spike
from src.onboarding.pipeline import build_catalog
from src.onboarding import pipeline
from src.knowledge.catalog_api import CatalogAPI
from src.knowledge.retrieval import SchemaRetriever, ValueIndex


class FakeLLM:
    def __init__(self, sql):
        self.sql = sql
        self.prompts = []

    def chat(self, system, user):
        self.prompts.append(user)
        return SimpleNamespace(text=json.dumps({"sql": self.sql, "reasoning": "catalog grounded"}), latency_ms=1)


def _db(path, *, declared_fk=True):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, customer_segment TEXT, email_address TEXT);
        CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL,
                               status, deleted_at TEXT);
        INSERT INTO customers VALUES (1, 'enterprise', 'sensitive-canary-4812@example.invalid');
        INSERT INTO invoices VALUES (10, 1, 25.0, 'paid', NULL);
        INSERT INTO invoices VALUES (11, 1, 30.0, 1, NULL);
    """)
    if declared_fk:
        # SQLite cannot add the declaration after CREATE; recreate invoices with the FK.
        connection.executescript("""
            CREATE TABLE invoice_copy (invoice_id INTEGER PRIMARY KEY, customer_id INTEGER,
                                       amount REAL, status, deleted_at TEXT,
                                       FOREIGN KEY(customer_id) REFERENCES customers(customer_id));
            INSERT INTO invoice_copy SELECT * FROM invoices;
            DROP TABLE invoices;
            ALTER TABLE invoice_copy RENAME TO invoices;
        """)
    connection.commit()
    connection.close()


def test_query_entrypoint_uses_retrieved_catalog_and_approved_join(monkeypatch, tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    _db(warehouse)
    monkeypatch.setattr(spike, "db_path", lambda _: warehouse)
    fake = FakeLLM("SELECT customers.customer_segment, invoices.amount, invoices.status FROM invoices JOIN customers ON invoices.customer_id = customers.customer_id")

    result = spike.answer(fake, "warehouse", "show customer segment, invoice amount, and invoice status", catalog_dir=tmp_path / "catalog", trace_path=tmp_path / "traces.json")

    assert result["status"] == "ok", result
    assert set(result["retrieved_tables"]) == {"customers", "invoices"}
    assert result["schema_tokens_estimated"] < 2000
    assert "APPROVED JOIN EDGES" in fake.prompts[0]
    assert "sensitive-canary-4812@example.invalid" not in fake.prompts[0]
    assert "email_address" not in fake.prompts[0]
    assert "possible soft-delete/active flag" in fake.prompts[0]
    assert "mixed formats" in fake.prompts[0]
    assert result["profile_warnings"]
    assert result["evidence_ledger"][0]["query_id"] == result["run_id"]
    assert result["synthesis"]["fact_check"]["passed"]
    trace = (tmp_path / "traces.json").read_text(encoding="utf-8")
    assert "sensitive-canary-4812@example.invalid" not in trace
    events = json.loads(trace)
    execution = next(event for event in events if event["step"] == "sql_validation_or_execution")
    assert execution["output"] == {"status": "ok", "column_count": 3, "row_count": 2}
    assert execution["duration_ms"] >= 0
    assert execution["tokens"] == {"input": 0, "output": 0}


def test_retrieval_trace_records_measured_duration_and_estimates(monkeypatch, tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    _db(warehouse)
    monkeypatch.setattr(spike, "db_path", lambda _: warehouse)
    clock_values = itertools.count(10.0, 0.125)
    monkeypatch.setattr(spike, "time", SimpleNamespace(perf_counter=lambda: next(clock_values)))
    fake = FakeLLM("SELECT customers.customer_segment FROM customers")
    question = "show customer segment"

    result = spike.answer(fake, "warehouse", question, catalog_dir=tmp_path / "catalog",
                          trace_path=tmp_path / "traces.json")

    retrieval = json.loads((tmp_path / "traces.json").read_text(encoding="utf-8"))[0]
    assert retrieval["step"] == "retrieval"
    assert retrieval["duration_ms"] == 125.0
    assert retrieval["tokens"] == {
        "schema_estimated": result["schema_tokens_estimated"],
        "question_characters": len(question),
    }


def test_query_entrypoint_builds_with_learned_encoder_and_recovers_reranker_failure(tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    _db(warehouse)

    class FixtureEmbedder:
        backend = "sentence_transformers_dense_v1"
        encoder_version = "fixture/semantic@v1"
        model_id = "fixture/semantic"
        revision = "v1"
        dimensions = 3

        def embed(self, text):
            lowered = text.casefold()
            if any(word in lowered for word in ("invoice", "billing", "amount")):
                return (1.0, 0.0, 0.0)
            if "customer" in lowered or "segment" in lowered:
                return (0.0, 1.0, 0.0)
            return (0.0, 0.0, 1.0)

    class BrokenReranker:
        def score(self, query, document):
            raise OSError("simulated model runtime failure")

    output = tmp_path / "catalog"
    result = spike.answer(FakeLLM("SELECT invoices.amount FROM invoices"), "warehouse",
                          "billing amount", catalog_dir=output, trace_path=tmp_path / "trace.json",
                          embedder=FixtureEmbedder(), reranker=BrokenReranker(),
                          warehouse_path=warehouse)

    payload = json.loads((output / "index_build.json").read_text(encoding="utf-8"))["dense"]
    assert payload["backend"] == "sentence_transformers_dense_v1"
    assert payload["encoder_version"] == "fixture/semantic@v1"
    assert result["status"] == "ok", result
    assert result["retrieval_mode"] == "hybrid_learned_reranker_fallback"


def test_runtime_embedding_failure_restarts_with_deterministic_hashed_index(tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    _db(warehouse)
    output = tmp_path / "catalog"
    build_catalog(warehouse, output)

    class BrokenEmbedder:
        from src.knowledge.dense_index import ENCODER_VERSION as encoder_version

        def embed(self, text):
            raise OSError("local runtime unavailable")

    first = SchemaRetriever(CatalogAPI(output / "catalog.json"), embedder=BrokenEmbedder())
    second = SchemaRetriever(CatalogAPI(output / "catalog.json"), embedder=BrokenEmbedder())
    result = first.retrieve("invoice amount")
    repeated = second.retrieve("invoice amount")
    assert result.tables == repeated.tables
    assert result.retrieval_mode == "hybrid_hashed_fallback"
    assert any("deterministic lexical retrieval" in warning["retrieval"] for warning in result.warnings)


def test_empty_question_and_empty_schema_are_clarified_and_redacted(monkeypatch, tmp_path):
    warehouse = tmp_path / "empty.sqlite"
    sqlite3.connect(warehouse).close()
    monkeypatch.setattr(spike, "db_path", lambda _: warehouse)

    result = spike.answer(FakeLLM("SELECT 1"), "warehouse", None,
                          catalog_dir=tmp_path / "catalog", trace_path=tmp_path / "traces.json")

    assert result["status"] == "clarify"
    retrieval = json.loads((tmp_path / "traces.json").read_text(encoding="utf-8"))[0]
    assert retrieval["input"] == ""
    assert isinstance(retrieval["duration_ms"], (int, float))
    assert retrieval["duration_ms"] >= 0
    assert retrieval["tokens"] == {"schema_estimated": 0, "question_characters": 0}


def test_retrieval_trace_redacts_sensitive_question_text(monkeypatch, tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    _db(warehouse)
    monkeypatch.setattr(spike, "db_path", lambda _: warehouse)
    question = "show customer for trace-canary@example.invalid"

    spike.answer(FakeLLM("SELECT customers.customer_segment FROM customers"), "warehouse", question,
                 catalog_dir=tmp_path / "catalog", trace_path=tmp_path / "traces.json")

    trace = (tmp_path / "traces.json").read_text(encoding="utf-8")
    event = json.loads(trace)[0]
    assert "trace-canary@example.invalid" not in trace
    assert event["input"] == "[REDACTED]"
    assert event["tokens"]["question_characters"] == len(question)


def test_unapproved_join_is_rejected_at_query_boundary(monkeypatch, tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    _db(warehouse, declared_fk=False)
    monkeypatch.setattr(spike, "db_path", lambda _: warehouse)
    monkeypatch.setattr(spike, "execute", lambda *args, **kwargs: pytest.fail("unapproved SQL reached execution"))
    fake = FakeLLM("SELECT customers.customer_segment, invoices.amount FROM invoices JOIN customers ON invoices.customer_id = customers.customer_id")

    result = spike.answer(fake, "warehouse", "show customer segment and invoice amount", catalog_dir=tmp_path / "catalog", trace_path=tmp_path / "traces.json")

    assert result["status"] == "failed"
    assert any("UNAPPROVED_JOIN" in step.get("error", "") for step in result["trace"]), result
    execution = next(event for event in json.loads((tmp_path / "traces.json").read_text(encoding="utf-8"))
                     if event["step"] == "sql_validation_or_execution")
    assert execution["output"]["status"] == "error"
    assert execution["duration_ms"] >= 0


def test_fuzzy_value_index_returns_confidence_and_sensitive_values_are_excluded(tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    _db(warehouse)
    build_catalog(warehouse, tmp_path / "catalog")
    api = CatalogAPI(tmp_path / "catalog" / "catalog.json")
    values = ValueIndex(api)
    assert not any("email" in item["column"] for item in values.link("sensitive-canary-4812@example.invalid"))
    assert all("confidence" in item for item in values.link("payed"))
    assert values.link("paid")[0]["confidence"] == 1
    retrieval = SchemaRetriever(api).retrieve("invoice status", quoted_values=["unmatched-value"])
    assert retrieval.retrieval_mode == "hybrid_hashed"
    assert retrieval.needs_clarification
    assert "unmatched-value" in retrieval.clarification


def test_sql_validator_rejects_join_without_approved_edge():
    with pytest.raises(spike.ValidationError, match="UNAPPROVED_JOIN"):
        spike.validate("SELECT a.id FROM a JOIN b ON a.id=b.id", {"a": ["id"], "b": ["id"]})
    with pytest.raises(spike.ValidationError, match="CATALOG_REQUIRED"):
        spike.execute("anything", "SELECT 1")
    with pytest.raises(spike.ValidationError, match="UNSAFE_STAR"):
        spike.validate("SELECT * FROM a", {"a": ["id"]})
    assert spike.validate("SELECT COUNT(*) FROM a", {"a": ["id"]}) == "SELECT COUNT(*) FROM a"


def test_token_budget_fails_closed_instead_of_truncating(tmp_path):
    warehouse = tmp_path / "large.sqlite"
    connection = sqlite3.connect(warehouse)
    columns = ", ".join(f"field_{i:04d} TEXT" for i in range(400))
    connection.execute(f"CREATE TABLE oversized ({columns})")
    connection.commit()
    connection.close()
    build_catalog(warehouse, tmp_path / "catalog")
    api = CatalogAPI(tmp_path / "catalog" / "catalog.json")
    from src.knowledge.retrieval import CONTEXT_TOKEN_BUDGET
    result = SchemaRetriever(api, token_budget=2).retrieve("oversized field")
    assert result.needs_clarification
    assert result.estimated_tokens > 2


def test_refresh_profiles_and_reindexes_only_changed_table(tmp_path):
    warehouse = tmp_path / "refresh.sqlite"
    connection = sqlite3.connect(warehouse)
    connection.executescript("CREATE TABLE first_table (id INTEGER PRIMARY KEY, value TEXT); CREATE TABLE second_table (id INTEGER PRIMARY KEY, value TEXT); INSERT INTO first_table VALUES (1, 'a'); INSERT INTO second_table VALUES (1, 'b');")
    connection.commit()
    connection.close()
    output = tmp_path / "catalog"
    build_catalog(warehouse, output)
    connection = sqlite3.connect(warehouse)
    connection.execute("INSERT INTO first_table VALUES (2, 'c')")
    connection.commit()
    connection.close()

    report = build_catalog(warehouse, output)

    assert report["changed_tables"] == ["first_table"]
    assert report["profiled_tables"] == ["first_table"]
    assert report["reindexed_tables"] == ["first_table"]
    api = CatalogAPI(output / "catalog.json")
    assert "second_table" in api.tables()
    assert any(item["name"] == "second_table.value" for item in api.search("second_table value"))


def test_refresh_detects_same_row_count_data_edits_without_watermark(tmp_path):
    warehouse = tmp_path / "same-count-refresh.sqlite"
    connection = sqlite3.connect(warehouse)
    connection.executescript("""
        CREATE TABLE first_table (id INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE second_table (id INTEGER PRIMARY KEY, value TEXT) WITHOUT ROWID;
        INSERT INTO first_table VALUES (1, 'old value');
        INSERT INTO second_table VALUES (1, 'untouched');
    """)
    connection.commit()
    connection.close()
    output = tmp_path / "catalog"
    build_catalog(warehouse, output)

    connection = sqlite3.connect(warehouse)
    connection.execute("UPDATE first_table SET value='new value' WHERE id=1")
    connection.commit()
    connection.close()
    report = build_catalog(warehouse, output)

    assert report["changed_tables"] == ["first_table"]
    assert report["profiled_tables"] == ["first_table"]
    assert report["reindexed_tables"] == ["first_table"]
    index = json.loads((output / "index_build.json").read_text(encoding="utf-8"))
    assert "new value" in index["value_index"]["first_table.value"]
    assert "old value" not in index["value_index"]["first_table.value"]


def test_unchanged_warehouse_reuses_table_signatures(monkeypatch, tmp_path):
    warehouse = tmp_path / "unchanged.sqlite"
    connection = sqlite3.connect(warehouse)
    connection.execute("CREATE TABLE accounts (account_id INTEGER PRIMARY KEY, label TEXT)")
    connection.execute("INSERT INTO accounts VALUES (1, 'active')")
    connection.commit()
    connection.close()
    output = tmp_path / "catalog"
    build_catalog(warehouse, output)
    monkeypatch.setattr(pipeline, "_table_signatures",
                        lambda *args: pytest.fail("unchanged source should reuse stored signatures"))

    report = build_catalog(warehouse, output)

    assert report["changed_tables"] == []
    assert report["profiled_tables"] == []
    assert report["reindexed_tables"] == []
