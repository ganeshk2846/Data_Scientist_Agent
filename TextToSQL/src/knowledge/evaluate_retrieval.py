"""Reproducible local evaluation for the pinned learned retrieval models.

Run only after explicitly installing the optional extra and caching the model
assets: ``python -m src.knowledge.evaluate_retrieval``.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from src.knowledge.catalog_api import CatalogAPI
from src.knowledge.retrieval import SchemaRetriever
from src.knowledge.semantic_models import (
    CrossEncoderReranker,
    SentenceTransformerEmbedder,
)
from src.onboarding.pipeline import build_catalog

EVAL_DATASET_ID = "be2-schema-paraphrases-v1"
CASES = (
    ("billing status", "invoices"),
    ("settlement condition", "invoices"),
    ("payment state", "invoices"),
    ("total amount charged", "invoices"),
    ("invoice total", "invoices"),
    ("customer segment", "customers"),
    ("buyer tier", "customers"),
    ("client category", "customers"),
    ("market group of customers", "customers"),
    ("product category", "products"),
    ("merchandise type", "products"),
    ("item class", "products"),
)


def evaluate(embedder, reranker=None) -> dict:
    """Measure recall@1/MRR against fixed table labels on an isolated fixture."""
    with tempfile.TemporaryDirectory(prefix="be2-retrieval-eval-") as temporary:
        root = Path(temporary)
        warehouse = root / "evaluation.sqlite"
        connection = sqlite3.connect(warehouse)
        connection.executescript("""
            CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, customer_segment TEXT);
            CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY, payment_status TEXT, amount REAL);
            CREATE TABLE products (product_id INTEGER PRIMARY KEY, product_category TEXT);
        """)
        connection.close()
        catalog_dir = root / "catalog"
        build_catalog(warehouse, catalog_dir, dense_encoder=embedder)
        retriever = SchemaRetriever(CatalogAPI(catalog_dir / "catalog.json"),
                                    embedder=embedder, reranker=reranker)
        reciprocal_ranks = []
        recalled_at_one = []
        for question, relevant_table in CASES:
            result = retriever.retrieve(question)
            try:
                rank = result.tables.index(relevant_table) + 1
            except ValueError:
                rank = 0
            reciprocal_ranks.append(1 / rank if rank else 0.0)
            recalled_at_one.append(rank == 1)
        return {
            "dataset": EVAL_DATASET_ID,
            "evaluation_scope": "12-case synthetic schema-paraphrase fixture; not a production corpus",
            "cases": len(CASES),
            "backend": getattr(embedder, "backend", type(embedder).__name__),
            "encoder_version": getattr(embedder, "encoder_version", "unversioned"),
            "reranker": getattr(reranker, "model_id", None),
            "reranker_revision": getattr(reranker, "revision", None),
            "evaluation_kind": ("pinned_model_fixture" if getattr(embedder, "model_id", None)
                                and getattr(embedder, "revision", None)
                                and (reranker is None or (getattr(reranker, "model_id", None)
                                                         and getattr(reranker, "revision", None)))
                                else "adapter_fixture"),
            "recall_at_1": sum(recalled_at_one) / len(CASES),
            "mrr": sum(reciprocal_ranks) / len(CASES),
            "retrieval_mode": retriever.mode,
            "reranker_failure": retriever._reranker_failure,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--without-reranker", action="store_true",
                        help="evaluate dense RRF without the cross-encoder")
    args = parser.parse_args()
    embedder = SentenceTransformerEmbedder.load_local()
    reranker = None if args.without_reranker else CrossEncoderReranker.load_local()
    print(json.dumps(evaluate(embedder, reranker), indent=2))


if __name__ == "__main__":
    main()
