"""Deterministic local retrieval evaluation (GRD-4/5/7/10)."""
import json
import sqlite3

import pytest

from src.knowledge.catalog_api import CatalogAPI
from src.knowledge.dense_index import build_dense_payload, valid_payload
from src.knowledge.retrieval import SchemaRetriever
from src.knowledge.semantic_models import (EMBEDDING_MODEL_REVISION, ModelAssetsUnavailable,
                                           ModelConfigurationError, ModelPin, SentenceTransformerEmbedder,
                                           configured_pin)
from src.onboarding.pipeline import build_catalog


CASES = (
    {"question": "invoice payment status", "relevant_tables": {"invoices"}},
    {"question": "customer segment", "relevant_tables": {"customers"}},
    {"question": "product category", "relevant_tables": {"products"}},
    {"question": "invoce paymnt staus", "relevant_tables": {"invoices"}},
    {"question": "custmer segmnt", "relevant_tables": {"customers"}},
    {"question": "prodct catagory", "relevant_tables": {"products"}},
)


def test_persisted_hybrid_retrieval_fixture_reports_recall_and_mrr(tmp_path):
    warehouse = tmp_path / "retrieval.sqlite"
    connection = sqlite3.connect(warehouse)
    connection.executescript("""
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, customer_segment TEXT);
        CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY, payment_status TEXT, amount REAL);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, product_category TEXT);
    """)
    connection.close()
    build_catalog(warehouse, tmp_path / "catalog")
    catalog = CatalogAPI(tmp_path / "catalog" / "catalog.json")
    retriever = SchemaRetriever(catalog)
    keyword_retriever = SchemaRetriever(catalog, use_dense=False)

    reciprocal_ranks = []
    recalled_at_one = []
    keyword_reciprocal_ranks = []
    keyword_recalled_at_one = []
    for case in CASES:
        result = retriever.retrieve(case["question"])
        assert not result.needs_clarification, result.clarification
        ranked_tables = list(result.tables)
        relevant_ranks = [rank for rank, table in enumerate(ranked_tables, start=1)
                          if table in case["relevant_tables"]]
        reciprocal_ranks.append(1 / min(relevant_ranks) if relevant_ranks else 0.0)
        recalled_at_one.append(bool(set(ranked_tables[:1]) & case["relevant_tables"]))
        assert result.retrieval_mode == "hybrid_hashed"
        keyword_result = keyword_retriever.retrieve(case["question"])
        keyword_ranks = [rank for rank, table in enumerate(keyword_result.tables, start=1)
                         if table in case["relevant_tables"]]
        keyword_reciprocal_ranks.append(1 / min(keyword_ranks) if keyword_ranks else 0.0)
        keyword_recalled_at_one.append(bool(set(keyword_result.tables[:1]) & case["relevant_tables"]))

    recall_at_1 = sum(recalled_at_one) / len(CASES)
    mean_reciprocal_rank = sum(reciprocal_ranks) / len(CASES)
    keyword_recall_at_1 = sum(keyword_recalled_at_one) / len(CASES)
    keyword_mrr = sum(keyword_reciprocal_ranks) / len(CASES)
    assert (recall_at_1, mean_reciprocal_rank) == (1.0, 1.0)
    assert (keyword_recall_at_1, keyword_mrr) == (0.5, 0.5)


def test_hybrid_adapter_uses_dense_rank_and_cross_encoder_reranker(tmp_path):
    warehouse = tmp_path / "hybrid.sqlite"
    connection = sqlite3.connect(warehouse)
    connection.executescript("""
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, customer_segment TEXT);
        CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY, payment_status TEXT);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, product_category TEXT);
    """)
    connection.close()
    build_catalog(warehouse, tmp_path / "hybrid-catalog")

    class TestEmbedder:
        def embed(self, text):
            text = text.casefold()
            billing = any(word in text for word in ("billing", "invoice", "payment"))
            customer = any(word in text for word in ("customer", "segment"))
            product = any(word in text for word in ("product", "category"))
            return (float(billing), float(customer), float(product))

    class TestReranker:
        def __init__(self):
            self.calls = []

        def score(self, query, document):
            self.calls.append((query, document))
            return float("invoice" in document.casefold())

    reranker = TestReranker()
    retriever = SchemaRetriever(
        CatalogAPI(tmp_path / "hybrid-catalog" / "catalog.json"),
        embedder=TestEmbedder(), reranker=reranker,
    )
    result = retriever.retrieve("billing")
    assert result.retrieval_mode == "hybrid_learned_reranked"
    assert result.tables[0] == "invoices"
    assert retriever.rrf_k == 60
    assert reranker.calls


def test_persisted_dense_index_is_versioned_rebuildable_and_fails_closed(tmp_path, monkeypatch):
    warehouse = tmp_path / "dense.sqlite"
    connection = sqlite3.connect(warehouse)
    connection.executescript("""
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, customer_segment TEXT);
        CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY, payment_status TEXT);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, product_category TEXT);
    """)
    connection.close()
    output = tmp_path / "dense-catalog"
    build_catalog(warehouse, output)
    index_path = output / "index_build.json"
    first = json.loads(index_path.read_text(encoding="utf-8"))["dense"]
    assert first["backend"] == "hashed_ngram_dense_v1"
    assert first["encoder_version"] == "signed-word-char-ngram-v1"
    assert first["index_version"].startswith("dense-")
    assert first["vectors"] and all(len(vector) == first["dimensions"] for vector in first["vectors"].values())

    build_catalog(warehouse, output)
    rebuilt = json.loads(index_path.read_text(encoding="utf-8"))["dense"]
    assert rebuilt["index_version"] == first["index_version"]
    api = CatalogAPI(output / "catalog.json")
    assert SchemaRetriever(api).retrieve("invoce paymnt staus").tables[0] == "invoices"

    corrupted = json.loads(index_path.read_text(encoding="utf-8"))
    first_vector = next(iter(corrupted["dense"]["vectors"].values()))
    first_vector[0] += 0.125
    index_path.write_text(json.dumps(corrupted), encoding="utf-8")
    fallback = SchemaRetriever(api)
    assert fallback.mode == "keyword_only_dense_unavailable"
    assert fallback.retrieve("invoce paymnt staus").needs_clarification

    build_catalog(warehouse, output)
    repaired = SchemaRetriever(CatalogAPI(output / "catalog.json"))
    assert repaired.mode == "hybrid_hashed"
    assert repaired.retrieve("invoce paymnt staus").tables[0] == "invoices"
    old_dense = json.loads(index_path.read_text(encoding="utf-8"))["dense"]
    connection = sqlite3.connect(warehouse)
    connection.execute("ALTER TABLE invoices ADD COLUMN payment_method TEXT")
    connection.commit()
    connection.close()
    report = build_catalog(warehouse, output)
    new_dense = json.loads(index_path.read_text(encoding="utf-8"))["dense"]
    unchanged = [key for key in old_dense["vectors"] if not key.endswith(":invoices") and not key.startswith("column:invoices.")]
    assert "invoices" in report["reindexed_tables"]
    assert new_dense["reused_vector_count"] >= len(unchanged)
    assert all(old_dense["vectors"][key] == new_dense["vectors"][key] for key in unchanged)
    assert new_dense["index_version"] != old_dense["index_version"]


def test_pinned_encoder_payload_persists_and_retrieves_with_matching_model(tmp_path, monkeypatch):
    class SemanticEncoder:
        backend = "sentence_transformers_dense_v1"
        encoder_version = "fixture/model@immutable-revision"
        model_id = "fixture/model"
        revision = "immutable-revision"
        dimensions = 3

        def embed(self, text):
            value = text.casefold()
            if any(word in value for word in ("invoice", "billing", "payment")):
                return (1.0, 0.0, 0.0)
            if any(word in value for word in ("customer", "segment")):
                return (0.0, 1.0, 0.0)
            if any(word in value for word in ("product", "category")):
                return (0.0, 0.0, 1.0)
            return (0.0, 0.0, 0.0)

    warehouse = tmp_path / "semantic.sqlite"
    connection = sqlite3.connect(warehouse)
    connection.executescript("""
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, customer_segment TEXT);
        CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY, payment_status TEXT);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, product_category TEXT);
    """)
    connection.close()
    output = tmp_path / "semantic-catalog"
    encoder = SemanticEncoder()
    report = build_catalog(warehouse, output, dense_encoder=encoder)
    payload = json.loads((output / "index_build.json").read_text(encoding="utf-8"))["dense"]
    assert report["store"]["embedding_model"] == encoder.encoder_version
    assert payload["backend"] == encoder.backend
    assert payload["model_id"] == encoder.model_id
    assert payload["model_revision"] == encoder.revision
    assert valid_payload(payload)

    retriever = SchemaRetriever(CatalogAPI(output / "catalog.json"), embedder=encoder)
    assert retriever.retrieve("billing state").tables[0] == "invoices"
    assert retriever._persisted_dense is not None

    monkeypatch.setenv("TEXTTOSQL_MODEL_CACHE", str(tmp_path / "empty-model-cache"))
    unavailable = SchemaRetriever(CatalogAPI(output / "catalog.json"))
    assert unavailable.mode == "keyword_only_fallback"
    result = unavailable.retrieve("billing state")
    assert result.retrieval_mode == "keyword_only_fallback"
    assert any("not cached" in warning["retrieval"] for warning in result.warnings)

    changed = SemanticEncoder()
    changed.encoder_version = "fixture/model@new-revision"
    changed.revision = "new-revision"
    build_catalog(warehouse, output, dense_encoder=changed)
    rebuilt = json.loads((output / "index_build.json").read_text(encoding="utf-8"))["dense"]
    assert rebuilt["encoder_version"] == changed.encoder_version
    assert rebuilt["reused_vector_count"] == 0
    with pytest.raises(ValueError, match="does not match"):
        SchemaRetriever(CatalogAPI(output / "catalog.json"), embedder=encoder)


def test_sentence_transformer_adapters_validate_real_library_shapes():
    from src.knowledge.semantic_models import CrossEncoderReranker, SentenceTransformerEmbedder

    class FakeSentenceModel:
        def get_sentence_embedding_dimension(self):
            return 3

        def encode(self, text, **kwargs):
            assert kwargs["normalize_embeddings"] is True
            return [1.0, 0.0, 0.0]

    class FakeCrossEncoder:
        def predict(self, pairs, **kwargs):
            assert pairs == [("question", "document")]
            return [0.75]

    embedder = SentenceTransformerEmbedder(FakeSentenceModel())
    assert embedder.dimensions == 3
    assert embedder.embed("question") == (1.0, 0.0, 0.0)
    reranker = CrossEncoderReranker(FakeCrossEncoder())
    assert reranker.score("question", "document") == 0.75


def test_reproducible_learned_model_evaluation_harness_reports_metrics():
    from src.knowledge.evaluate_retrieval import evaluate

    class FixtureSemanticEncoder:
        backend = "sentence_transformers_dense_v1"
        encoder_version = "fixture/eval@v1"
        dimensions = 3

        def embed(self, text):
            text = text.casefold()
            if any(term in text for term in ("invoice", "billing", "settlement", "payment", "amount", "charged")):
                return (1.0, 0.0, 0.0)
            if any(term in text for term in ("customer", "segment", "buyer", "client", "market group")):
                return (0.0, 1.0, 0.0)
            return (0.0, 0.0, 1.0)

    result = evaluate(FixtureSemanticEncoder())

    assert result["dataset"] == "be2-schema-paraphrases-v1"
    assert result["cases"] == 12
    assert result["encoder_version"] == "fixture/eval@v1"
    assert result["recall_at_1"] == 1.0
    assert result["mrr"] == 1.0


def test_model_pins_require_immutable_revision_and_overrides_are_explicit(monkeypatch):
    assert ModelPin("org/model", "a" * 40).revision == "a" * 40
    with pytest.raises(ModelConfigurationError, match="40-character"):
        ModelPin("org/model", "main")
    monkeypatch.setenv("TEXTTOSQL_EMBEDDING_MODEL_ID", "org/model")
    monkeypatch.delenv("TEXTTOSQL_EMBEDDING_MODEL_REVISION", raising=False)
    with pytest.raises(ModelConfigurationError, match="REVISION is required"):
        configured_pin("embedding", "default/model", EMBEDDING_MODEL_REVISION)
    monkeypatch.setenv("TEXTTOSQL_EMBEDDING_MODEL_REVISION", "b" * 40)
    assert configured_pin("embedding", "default/model", EMBEDDING_MODEL_REVISION) == ModelPin("org/model", "b" * 40)


def test_model_loader_reports_missing_pinned_cache_without_network(monkeypatch, tmp_path):
    monkeypatch.delenv("TEXTTOSQL_MODEL_CACHE", raising=False)
    with pytest.raises(ModelAssetsUnavailable, match="not cached"):
        SentenceTransformerEmbedder.load_local(cache_folder=str(tmp_path / "empty"))


def test_explicit_model_downloader_reports_network_failure_without_hiding_pin(monkeypatch, tmp_path):
    import sys
    from types import ModuleType
    from src.knowledge.model_assets import download_models

    hub = ModuleType("huggingface_hub")
    def unavailable(**kwargs):
        raise ConnectionError("offline")
    hub.snapshot_download = unavailable
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    with pytest.raises(RuntimeError, match="Could not provision pinned model"):
        download_models(tmp_path / "model-cache")
